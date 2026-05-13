from typing import List, Dict, Any, Optional
from app.schemas.datasheet import EvaluateDatasheetRequest, EvaluateDatasheetResultItem, DimensionResult
from app.services.basic_operations_service import BasicOperationsService
from app.models import Rate, Quota
from app.models.quota import OverageCost
from app.services.budget_service import BudgetService

_budget_service = BudgetService()
from app.engine.time_models import TimeDuration, TimeUnit

# Campos propios de un endpoint — todo lo que no esté aquí es un alias
_KNOWN_ENDPOINT_KEYS = {"rate", "quota", "workload", "cost_per_request"}

# Operaciones que devuelven estructuras propias y no deben pasar por el dimension logic
_NON_DIMENSIONAL_OPS = {"quota_exhaustion_threshold", "idle_time_period"}

# Alias de nombres de unidad v0.3 → nombre del enum TimeUnit
_UNIT_ALIASES = {"MIN": "MINUTE"}


class DatasheetEvaluatorService:
    def __init__(self):
        self.basic_ops_service = BasicOperationsService()

    def _normalize_period(self, period_def) -> TimeDuration:
        """Soporta period como string v0.2 ('1min') y como objeto v0.3 ({value, unit})."""
        if isinstance(period_def, dict):
            value = period_def["value"]
            unit_str = str(period_def["unit"]).upper()
            unit_str = _UNIT_ALIASES.get(unit_str, unit_str)
            return TimeDuration(value, TimeUnit[unit_str])
        # v0.2: string "1 min", "1 month", etc. — lo pasa el validator de Rate/Quota
        return str(period_def).replace(" ", "")

    def _parse_rate(self, rate_key: str, max_power_defs: dict) -> Rate:
        if rate_key not in max_power_defs:
            raise KeyError(f"Rate definition '{rate_key}' not found in max_power definitions.")
        r_def = max_power_defs[rate_key]
        return Rate(
            value=float(r_def["value"]),
            unit=str(r_def["unit"]),
            period=self._normalize_period(r_def["period"])
        )

    def _parse_quota(self, quota_key: str, capacity_defs: dict) -> Quota:
        if quota_key not in capacity_defs:
            raise KeyError(f"Quota definition '{quota_key}' not found in capacity definitions.")
        q_def = capacity_defs[quota_key]
        overage_cost = None
        if oc := q_def.get("overage_cost"):
            overage_cost = OverageCost(price=float(oc["price"]), value=float(oc.get("value", 1.0)))
        return Quota(
            value=float(q_def["value"]),
            unit=str(q_def["unit"]),
            period=self._normalize_period(q_def["period"]),
            overage_cost=overage_cost,
        )

    def _parse_rates(self, rate_def, max_power_defs: dict) -> List[Rate]:
        """Acepta un string o una lista de strings y devuelve siempre List[Rate]."""
        keys = rate_def if isinstance(rate_def, list) else [rate_def]
        return [self._parse_rate(k, max_power_defs) for k in keys]

    def _parse_quotas(self, quota_def, capacity_defs: dict) -> List[Quota]:
        """Acepta un string o una lista de strings y devuelve siempre List[Quota]."""
        keys = quota_def if isinstance(quota_def, list) else [quota_def]
        return [self._parse_quota(k, capacity_defs) for k in keys]

    def _parse_workload(self, workload_def) -> Optional[List[dict]]:
        """Returns list of {'unit': str, 'min': float, 'max': float} or None."""
        if not workload_def:
            return None
        items = workload_def if isinstance(workload_def, list) else [workload_def]
        return [
            {'unit': str(w['unit']), 'min': float(w['min']), 'max': float(w['max'])}
            for w in items
        ]

    def _build_scenarios(
        self,
        rates: List[Rate],
        quotas: List[Quota],
        workload: dict,
        capacity_request_factor: Optional[Dict[str, float]],
    ) -> List[tuple]:
        """
        Returns list of (scenario_name, dimension, rates, quotas).

        Builds two dimensions per workload scenario:
          - 'requests': req-rates stay, wl-unit rates divided by w; wl-unit quotas floor-divided by w
          - workload.unit (e.g. 'emails'): wl-quotas stay, req-rates multiplied by w

        Effective max workload is capped at the smallest quota in wl_unit so a single
        request never exhausts the periodic quota in one call.
        Quotas in other units (e.g. MBs without a workload) are omitted with a warning.
        """
        wl_unit = workload['unit']
        wl_min  = workload['min']
        wl_max  = workload['max']

        # Apply ceiling: max workload ≤ smallest quota in wl_unit
        quotas_wl = [q for q in quotas if q.unit == wl_unit]
        if quotas_wl:
            min_quota_val = min(q.value for q in quotas_wl)
            wl_max_eff = max(wl_min, min(wl_max, min_quota_val))
        else:
            wl_max_eff = wl_max

        # Determine scenario workload values
        if capacity_request_factor and wl_unit in capacity_request_factor:
            wl_values = [("fixed", capacity_request_factor[wl_unit])]
        elif wl_min == wl_max_eff:
            wl_values = [("fixed", wl_min)]
        else:
            wl_avg = (wl_min + wl_max_eff) / 2
            if wl_min == int(wl_min) and wl_max_eff == int(wl_max_eff):
                wl_avg = round(wl_avg)
            # exclude zero-workload values to avoid division by zero
            candidates = [("worst", wl_min), ("avg", wl_avg), ("best", wl_max_eff)]
            wl_values = [(name, w) for name, w in candidates if w > 0]

        # Classify limits by unit — quotas/rates of OTHER workload units are silently
        # ignored here; they are processed by their own _build_scenarios call.
        rates_req  = [r for r in rates  if r.unit == "requests"]
        rates_wl   = [r for r in rates  if r.unit == wl_unit]
        quotas_req = [q for q in quotas if q.unit == "requests"]

        print(f"[DIM] wl_unit={wl_unit} wl_min={wl_min} wl_max={wl_max} wl_max_eff={wl_max_eff} scenarios={[v for _, v in wl_values]}")

        scenarios = []
        for sc_name, w in wl_values:
            # ── requests dimension ────────────────────────────────────────────
            sc_rates_req = list(rates_req)
            for r in rates_wl:
                sc_rates_req.append(Rate(value=max(1, round(r.value / w)), unit="requests", period=r.period))

            sc_quotas_req = list(quotas_req)
            skip_req = False
            for q in quotas_wl:
                cv = int(q.value // w)
                if cv < 1:
                    skip_req = True
                    break
                sc_quotas_req.append(Quota(value=cv, unit="requests", period=q.period))

            if not skip_req and (sc_rates_req or sc_quotas_req):
                print(f"[DIM]   w={w} → requests: rates={[(r.value, r.unit, r.period) for r in sc_rates_req]} quotas={[(q.value, q.unit, q.period) for q in sc_quotas_req]}")
                scenarios.append((sc_name, "requests", sc_rates_req, sc_quotas_req, w, wl_unit))
            else:
                print(f"[DIM]   w={w} → requests: SKIPPED (quota converts to <1 req)")

            # ── workload-unit dimension ───────────────────────────────────────
            sc_rates_wl = list(rates_wl)
            for r in rates_req:
                sc_rates_wl.append(Rate(value=r.value * w, unit=wl_unit, period=r.period))

            sc_quotas_wl = list(quotas_wl)

            if sc_rates_wl or sc_quotas_wl:
                print(f"[DIM]   w={w} → {wl_unit}: rates={[(r.value, r.unit, r.period) for r in sc_rates_wl]} quotas={[(q.value, q.unit, q.period) for q in sc_quotas_wl]}")
                scenarios.append((sc_name, wl_unit, sc_rates_wl, sc_quotas_wl, w, wl_unit))

        return scenarios

    def _get_node_scenarios(
        self,
        node_config: dict,
        capacity_defs: dict,
        max_power_defs: dict,
        inherited_rates: List[Rate],
        inherited_quotas: List[Quota],
        capacity_unit: Optional[str] = None,
        capacity_request_factor: Optional[Dict[str, float]] = None,
    ) -> List[tuple]:
        """
        Returns List of (sc_name, dimension, rates, quotas, wf) for a leaf node.
        Used by both _process_node and get_curve_scenarios.
        """
        rates: List[Rate] = list(inherited_rates)
        if rate_def := node_config.get("rate"):
            rates.extend(self._parse_rates(rate_def, max_power_defs))
        quotas: List[Quota] = list(inherited_quotas)
        if quota_def := node_config.get("quota"):
            quotas.extend(self._parse_quotas(quota_def, capacity_defs))

        workloads = self._parse_workload(node_config.get("workload"))

        if not workloads:
            unit = rates[0].unit if rates else quotas[0].unit
            return [("fixed", unit, rates, quotas, None, None)]

        scenarios = []
        for wl in workloads:
            scenarios.extend(self._build_scenarios(rates, quotas, wl, capacity_request_factor))

        if capacity_unit:
            available = list({sc[1] for sc in scenarios})
            if capacity_unit not in available:
                raise ValueError(f"capacity_unit '{capacity_unit}' is not available. Available dimensions: {available}")
            scenarios = [sc for sc in scenarios if sc[1] == capacity_unit]

        return scenarios

    # ── Navigation helpers ────────────────────────────────────────────────────

    def get_plan_pricing(self, yaml_data: dict, plan_name: str) -> dict:
        """Returns {price, period_ms, currency} for a plan."""
        plans = yaml_data.get("plans", {})
        if plan_name not in plans:
            raise KeyError(f"Plan '{plan_name}' not found.")
        plan_data = plans[plan_name]
        currency = str(yaml_data.get("currency", "USD"))
        price = float(plan_data.get("price", 0.0))
        period_def = plan_data.get("period") or plan_data.get("billing_period") or {"value": 1, "unit": "MONTH"}
        period_ms = self._normalize_period(period_def)
        if isinstance(period_ms, str):
            from app.utils.time_utils import parse_time_string_to_duration
            period_ms = parse_time_string_to_duration(period_ms).to_milliseconds()
        else:
            period_ms = period_ms.to_milliseconds()
        return {"price": price, "period_ms": period_ms, "currency": currency}

    def get_plans(self, yaml_data: dict) -> List[str]:
        return list(yaml_data.get("plans", {}).keys())

    def get_endpoints(self, yaml_data: dict, plan_names: Optional[List[str]] = None) -> List[str]:
        plans = yaml_data.get("plans", {})
        if plan_names:
            unknown = [p for p in plan_names if p not in plans]
            if unknown:
                raise KeyError(f"Plans not found: {unknown}. Available: {list(plans.keys())}")
            plans_to_scan = {k: plans[k] for k in plan_names}
        else:
            plans_to_scan = plans
        seen: list = []
        for plan_data in plans_to_scan.values():
            for ep in (plan_data.get("endpoints") or {}).keys():
                if ep not in seen:
                    seen.append(ep)
        return seen

    def get_capacity_units(self, yaml_data: dict, plan_names: Optional[List[str]] = None, endpoint_path: Optional[str] = None) -> List[str]:
        plans = yaml_data.get("plans", {})
        if plan_names:
            unknown = [p for p in plan_names if p not in plans]
            if unknown:
                raise KeyError(f"Plans not found: {unknown}. Available: {list(plans.keys())}")
            plans_to_scan = {k: plans[k] for k in plan_names}
        else:
            plans_to_scan = plans
        seen: list = []
        for plan_data in plans_to_scan.values():
            endpoints_data = plan_data.get("endpoints") or {}
            if endpoint_path:
                if endpoint_path not in endpoints_data:
                    continue
                endpoints_to_scan = {endpoint_path: endpoints_data[endpoint_path]}
            else:
                endpoints_to_scan = endpoints_data
            for ep_config in endpoints_to_scan.values():
                ep_config = ep_config or {}
                if self._has_aliases(ep_config):
                    ep_workload = ep_config.get("workload") or []
                    alias_entries = {k: v for k, v in ep_config.items() if k not in _KNOWN_ENDPOINT_KEYS and isinstance(v, dict)}
                    workloads = list(ep_workload)
                    for alias_config in alias_entries.values():
                        for w in (alias_config.get("workload") or []):
                            if not any(x["unit"] == w["unit"] for x in workloads):
                                workloads.append(w)
                else:
                    workloads = ep_config.get("workload") or []
                for w in workloads:
                    u = str(w["unit"])
                    if u not in seen:
                        seen.append(u)
        return seen

    def get_aliases(self, yaml_data: dict, plan_names: Optional[List[str]] = None, endpoint_path: Optional[str] = None) -> Optional[List[str]]:
        plans = yaml_data.get("plans", {})
        if plan_names:
            unknown = [p for p in plan_names if p not in plans]
            if unknown:
                raise KeyError(f"Plans not found: {unknown}. Available: {list(plans.keys())}")
            plans_to_scan = {k: plans[k] for k in plan_names}
        else:
            plans_to_scan = plans
        seen: list = []
        for plan_data in plans_to_scan.values():
            endpoints_data = plan_data.get("endpoints") or {}
            eps = {endpoint_path: endpoints_data[endpoint_path]} if endpoint_path and endpoint_path in endpoints_data else endpoints_data
            for ep_config in eps.values():
                ep_config = ep_config or {}
                if self._has_aliases(ep_config):
                    for k, v in ep_config.items():
                        if k not in _KNOWN_ENDPOINT_KEYS and isinstance(v, dict) and k not in seen:
                            seen.append(k)
        return seen if seen else None

    def _collect_workloads_from_ep(self, ep_config: dict) -> list:
        """Extracts raw workload dicts from an endpoint config, handling aliases."""
        if self._has_aliases(ep_config):
            raw = list(ep_config.get("workload") or [])
            for k, v in ep_config.items():
                if k not in _KNOWN_ENDPOINT_KEYS and isinstance(v, dict):
                    for w in (v.get("workload") or []):
                        if not any(x["unit"] == w["unit"] for x in raw):
                            raw.append(w)
        else:
            raw = list(ep_config.get("workload") or [])
        return raw

    def get_crf_ranges(self, yaml_data: dict, plan_names: Optional[List[str]] = None, endpoint_path: Optional[str] = None) -> List[Dict[str, Any]]:
        plans = yaml_data.get("plans", {})
        if plan_names:
            unknown = [p for p in plan_names if p not in plans]
            if unknown:
                raise KeyError(f"Plans not found: {unknown}. Available: {list(plans.keys())}")
            plans_to_scan = {k: plans[k] for k in plan_names}
        else:
            plans_to_scan = plans
        # Collect broadest range per unit across all matching plans/endpoints
        ranges: Dict[str, Dict[str, Any]] = {}
        for plan_data in plans_to_scan.values():
            endpoints_data = plan_data.get("endpoints") or {}
            eps = {endpoint_path: endpoints_data[endpoint_path]} if endpoint_path and endpoint_path in endpoints_data else endpoints_data
            for ep_config in eps.values():
                for w in self._collect_workloads_from_ep(ep_config or {}):
                    unit = str(w["unit"])
                    wmin, wmax = float(w["min"]), float(w["max"])
                    if unit not in ranges:
                        ranges[unit] = {"unit": unit, "min": wmin, "max": wmax}
                        if w.get("description"):
                            ranges[unit]["description"] = str(w["description"])
                    else:
                        ranges[unit]["min"] = min(ranges[unit]["min"], wmin)
                        ranges[unit]["max"] = max(ranges[unit]["max"], wmax)
        return list(ranges.values())

    def get_curve_scenarios(
        self,
        yaml_data: dict,
        request: EvaluateDatasheetRequest,
        capacity_unit: Optional[str] = None,
        capacity_request_factor: Optional[Dict[str, float]] = None,
    ) -> List[dict]:
        """
        Returns a flat list of scenario dicts, each with:
          plan, endpoint, alias, dimension, crf, rates, quotas
        Ready for capacity curve rendering.
        """
        capacity_defs  = yaml_data.get("capacity", {}) or {}
        max_power_defs = yaml_data.get("max_power", {}) or {}
        plans = yaml_data.get("plans", {})

        if request.plan_names:
            unknown = [p for p in request.plan_names if p not in plans]
            if unknown:
                raise KeyError(f"Plans not found: {unknown}. Valid plans: {list(plans.keys())}")
            plans_to_process = {k: plans[k] for k in request.plan_names}
        else:
            plans_to_process = plans

        result = []

        for plan_name, plan_data in plans_to_process.items():
            endpoints_data = plan_data.get("endpoints", {}) or {}

            plan_rates: List[Rate] = []
            plan_quotas: List[Quota] = []
            if plan_rate_def := plan_data.get("rate"):
                plan_rates.extend(self._parse_rates(plan_rate_def, max_power_defs))
            if plan_quota_def := plan_data.get("quota"):
                plan_quotas.extend(self._parse_quotas(plan_quota_def, capacity_defs))

            target_endpoints = (
                {request.endpoint_path: endpoints_data[request.endpoint_path]}
                if request.endpoint_path else endpoints_data
            )

            for ep_path, ep_config in target_endpoints.items():
                ep_config = ep_config or {}

                if self._has_aliases(ep_config):
                    ep_rates = list(plan_rates)
                    ep_quotas = list(plan_quotas)
                    if ep_rate_def := ep_config.get("rate"):
                        ep_rates.extend(self._parse_rates(ep_rate_def, max_power_defs))
                    if ep_quota_def := ep_config.get("quota"):
                        ep_quotas.extend(self._parse_quotas(ep_quota_def, capacity_defs))

                    alias_entries = {
                        k: v for k, v in ep_config.items()
                        if k not in _KNOWN_ENDPOINT_KEYS and isinstance(v, dict)
                    }
                    if request.alias:
                        alias_entries = {request.alias: alias_entries[request.alias]}

                    ep_workload = ep_config.get("workload")
                    for alias_name, alias_config in alias_entries.items():
                        effective = {**alias_config, "workload": ep_workload} if ep_workload and "workload" not in alias_config else alias_config
                        for sc in self._get_node_scenarios(effective, capacity_defs, max_power_defs, ep_rates, ep_quotas, capacity_unit, capacity_request_factor):
                            result.append({"plan": plan_name, "endpoint": ep_path, "alias": alias_name,
                                           "dimension": sc[1], "crf": sc[4], "rates": sc[2], "quotas": sc[3], "workload_unit": sc[5]})
                else:
                    for sc in self._get_node_scenarios(ep_config, capacity_defs, max_power_defs, plan_rates, plan_quotas, capacity_unit, capacity_request_factor):
                        result.append({"plan": plan_name, "endpoint": ep_path, "alias": None,
                                       "dimension": sc[1], "crf": sc[4], "rates": sc[2], "quotas": sc[3], "workload_unit": sc[5]})

        return result

    def _has_aliases(self, ep_config: dict) -> bool:
        """Detecta si un endpoint tiene aliases (sub-dicts que no son campos conocidos)."""
        if ep_config is None:
            return False
        return any(
            isinstance(v, dict) and k not in _KNOWN_ENDPOINT_KEYS
            for k, v in ep_config.items()
        )

    def evaluate(self, yaml_data: dict, request: EvaluateDatasheetRequest,
                 capacity_unit: Optional[str] = None,
                 capacity_request_factor: Optional[Dict[str, float]] = None,
                 provider_mode: bool = False,
                 max_budget: Optional[float] = None,
                 exclude_plan_price: bool = False) -> Dict[str, List[EvaluateDatasheetResultItem]]:
        capacity_defs  = yaml_data.get("capacity", {}) or {}
        max_power_defs = yaml_data.get("max_power", {}) or {}
        plans = yaml_data.get("plans", {})

        if request.plan_names:
            unknown = [p for p in request.plan_names if p not in plans]
            if unknown:
                raise KeyError(f"Plans not found: {unknown}. Valid plans: {list(plans.keys())}")
            plans_to_process = {k: plans[k] for k in request.plan_names}
        else:
            plans_to_process = plans

        results: Dict[str, List[EvaluateDatasheetResultItem]] = {}

        for plan_name, plan_data in plans_to_process.items():
            results[plan_name] = self._evaluate_plan(
                plan_name=plan_name,
                plan_data=plan_data,
                capacity_defs=capacity_defs,
                max_power_defs=max_power_defs,
                request=request,
                capacity_unit=capacity_unit,
                capacity_request_factor=capacity_request_factor,
                provider_mode=provider_mode,
                max_budget=max_budget,
                exclude_plan_price=exclude_plan_price,
            )

        return results

    def _evaluate_plan(self, plan_name: str, plan_data: dict, capacity_defs: dict,
                       max_power_defs: dict, request: EvaluateDatasheetRequest,
                       capacity_unit: Optional[str] = None,
                       capacity_request_factor: Optional[Dict[str, float]] = None,
                       provider_mode: bool = False,
                       max_budget: Optional[float] = None,
                       exclude_plan_price: bool = False) -> List[EvaluateDatasheetResultItem]:
        plan_price = float(plan_data.get("price", 0.0))
        endpoints_data = plan_data.get("endpoints", {}) or {}

        plan_rates: List[Rate] = []
        plan_quotas: List[Quota] = []
        if plan_rate_def := plan_data.get("rate"):
            plan_rates.extend(self._parse_rates(plan_rate_def, max_power_defs))
        if plan_quota_def := plan_data.get("quota"):
            plan_quotas.extend(self._parse_quotas(plan_quota_def, capacity_defs))

        if request.endpoint_path:
            if request.endpoint_path not in endpoints_data:
                valid_eps = list(endpoints_data.keys())
                raise KeyError(f"Endpoint '{request.endpoint_path}' not found in plan '{plan_name}'. Valid endpoints are: {valid_eps}")
            target_endpoints = {request.endpoint_path: endpoints_data[request.endpoint_path]}
        else:
            target_endpoints = endpoints_data

        results = []

        for ep_path, ep_config in target_endpoints.items():
            ep_config = ep_config or {}

            if self._has_aliases(ep_config):
                ep_rates = list(plan_rates)
                ep_quotas = list(plan_quotas)
                if ep_rate_def := ep_config.get("rate"):
                    ep_rates.extend(self._parse_rates(ep_rate_def, max_power_defs))
                if ep_quota_def := ep_config.get("quota"):
                    ep_quotas.extend(self._parse_quotas(ep_quota_def, capacity_defs))

                alias_entries = {
                    k: v for k, v in ep_config.items()
                    if k not in _KNOWN_ENDPOINT_KEYS and isinstance(v, dict)
                }

                if request.alias:
                    if request.alias not in alias_entries:
                        raise KeyError(f"Alias '{request.alias}' not found in endpoint '{ep_path}'. Valid aliases are: {list(alias_entries.keys())}")
                    alias_entries = {request.alias: alias_entries[request.alias]}

                ep_workload = ep_config.get("workload")
                for alias_name, alias_config in alias_entries.items():
                    effective = {**alias_config, "workload": ep_workload} if ep_workload and "workload" not in alias_config else alias_config
                    res = self._process_node(
                        node_config=effective,
                        capacity_defs=capacity_defs,
                        max_power_defs=max_power_defs,
                        inherited_rates=ep_rates,
                        inherited_quotas=ep_quotas,
                        operation=request.operation,
                        operation_params=request.operation_params,
                        capacity_unit=capacity_unit,
                        capacity_request_factor=capacity_request_factor,
                        provider_mode=provider_mode,
                        max_budget=max_budget,
                        exclude_plan_price=exclude_plan_price,
                        plan_price=plan_price,
                    )
                    results.append(EvaluateDatasheetResultItem(
                        endpoint=ep_path, alias=alias_name, result=res
                    ))
            else:
                if request.alias:
                    raise ValueError(f"Endpoint '{ep_path}' has no aliases, but an alias was provided.")

                res = self._process_node(
                    node_config=ep_config,
                    capacity_defs=capacity_defs,
                    max_power_defs=max_power_defs,
                    inherited_rates=plan_rates,
                    inherited_quotas=plan_quotas,
                    operation=request.operation,
                    operation_params=request.operation_params,
                    capacity_unit=capacity_unit,
                    capacity_request_factor=capacity_request_factor,
                    provider_mode=provider_mode,
                    max_budget=max_budget,
                    exclude_plan_price=exclude_plan_price,
                    plan_price=plan_price,
                )
                results.append(EvaluateDatasheetResultItem(
                    endpoint=ep_path, alias=None, result=res
                ))

        return results

    def _process_node(self, node_config: dict, capacity_defs: dict, max_power_defs: dict,
                      inherited_rates: List[Rate], inherited_quotas: List[Quota],
                      operation: str, operation_params: dict,
                      capacity_unit: Optional[str] = None,
                      capacity_request_factor: Optional[Dict[str, float]] = None,
                      provider_mode: bool = False,
                      max_budget: Optional[float] = None,
                      exclude_plan_price: bool = False,
                      plan_price: float = 0.0) -> Any:

        rates: List[Rate] = list(inherited_rates)
        if rate_def := node_config.get("rate"):
            rates.extend(self._parse_rates(rate_def, max_power_defs))

        quotas: List[Quota] = list(inherited_quotas)
        if quota_def := node_config.get("quota"):
            quotas.extend(self._parse_quotas(quota_def, capacity_defs))

        if not rates and not quotas:
            raise ValueError(f"Neither rate nor quota could be resolved for node config: {node_config}")

        if max_budget is not None and quotas:
            quotas, _, _ = _budget_service.expand_quotas(quotas, plan_price, max_budget, exclude_plan_price)

        # Resolve method — get_ operations bypass dimension logic entirely
        method_name = f"calculate_{operation}"
        is_calc = hasattr(self.basic_ops_service, method_name)
        if not is_calc:
            method_name = f"get_{operation}"
        if not hasattr(self.basic_ops_service, method_name):
            raise ValueError(f"Operation '{operation}' is not supported. Engine has no calculate_{operation} or get_{operation} method.")

        method = getattr(self.basic_ops_service, method_name)

        if not is_calc:
            kwargs = dict(operation_params)
            kwargs["rate"]  = rates if rates else None
            kwargs["quota"] = quotas if quotas else None
            try:
                return method(**kwargs)
            except TypeError as e:
                raise ValueError(f"Invalid parameters for operation '{operation}': {str(e)}")

        # calculate_ operations — build dimensions when workload is present
        workload = self._parse_workload(node_config.get("workload"))

        if not workload:
            kwargs = dict(operation_params)
            kwargs["rate"]  = rates if rates else None
            kwargs["quota"] = quotas if quotas else None
            if is_calc:
                kwargs["provider_mode"] = provider_mode
            try:
                result = method(**kwargs)
            except TypeError as e:
                raise ValueError(f"Invalid parameters for operation '{operation}': {str(e)}")
            unit = rates[0].unit if rates else quotas[0].unit
            return [DimensionResult(dimension=unit, workload_factor=None, value=result)]

        scenarios = []
        for wl in workload:
            scenarios.extend(self._build_scenarios(rates, quotas, wl, capacity_request_factor))

        if capacity_unit:
            available = list({sc[1] for sc in scenarios})
            if capacity_unit not in available:
                raise ValueError(f"capacity_unit '{capacity_unit}' is not available. Available dimensions: {available}")

        dimension_results = []
        for sc_name, dimension, sc_rates, sc_quotas, wf, *_ in scenarios:
            if capacity_unit and dimension != capacity_unit:
                continue
            kwargs = dict(operation_params)
            kwargs["rate"]  = sc_rates if sc_rates else None
            kwargs["quota"] = sc_quotas if sc_quotas else None
            kwargs["provider_mode"] = provider_mode
            print(f"[BR] dimension='{dimension}' workload_factor={wf} → rates={[(r.value, r.unit) for r in sc_rates]} quotas={[(q.value, q.unit) for q in sc_quotas]}")
            try:
                value = method(**kwargs)
                print(f"[BR]   result={value}")
                dimension_results.append(DimensionResult(dimension=dimension, workload_factor=wf, value=value))
            except (ValueError, TypeError) as e:
                print(f"[BR]   SKIPPED: {e}")

        return dimension_results
