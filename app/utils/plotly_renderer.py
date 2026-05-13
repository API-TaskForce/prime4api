from typing import Literal

import plotly.graph_objects as go

from app.engine.plotters.curve_models import CapacityCurvePoints
from app.utils.time_utils import format_time_with_unit, select_best_time_unit

LineShape = Literal["hv", "linear"]
# "hv"     → escalón (step function). Usar para accumulated_curve e inflection_point_curve.
# "linear" → línea recta entre puntos. Usar para normalized_inflection_curve.


def render_capacity_curve_html(
    points: CapacityCurvePoints,
    title: str,
    line_shape: LineShape,
    x_unit_label: str,
    x_scale_divisor: float,
) -> str:
    """
    Convierte CapacityCurvePoints en un HTML Plotly autocontenido.

    Parámetros:
      points          : puntos generados por cualquier plotter.
      title           : título del gráfico.
      line_shape      : "hv" para escalón, "linear" para recta.
      x_unit_label    : etiqueta del eje X, e.g. "h", "day", "min".
      x_scale_divisor : divisor para convertir t_ms al eje visual.
                        e.g. si x_unit_label="h", x_scale_divisor=3_600_000.
                        Calculado por el service usando select_best_time_unit().

    Retorna:
      str con HTML completo (full_html=True, plotlyjs via CDN).
      Apto para devolver directamente desde un endpoint FastAPI como text/html.
    """
    xs = [t / x_scale_divisor for t in points.t_ms]
    ys = points.capacity

    # Color de relleno semitransparente (verde)
    fill_color = "rgba(0, 128, 0, 0.2)"
    line_color = "green"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs,
        y=ys,
        mode="lines",
        line=dict(color=line_color, shape=line_shape, width=1.5),
        fill="tozeroy",
        fillcolor=fill_color,
        name="Capacity",
    ))

    fig.update_layout(
        title=title,
        xaxis_title=f"Time ({x_unit_label})",
        yaxis_title="Accumulated Capacity",
        legend_title="Curves",
        showlegend=True,
        template="plotly_white",
        width=1000,
        height=600,
    )

    return fig.to_html(full_html=True, include_plotlyjs="cdn")


def render_multi_curve_html(
    series_list: list,
    title: str,
    line_shape: LineShape,
    x_unit_label: str,
    x_scale_divisor: float,
) -> str:
    """
    Renders capacity curves with hierarchical navigation:
      Plan → Endpoint → Dimension (workload units only) → CRF
    When an endpoint has multiple workload units a "Combined" tab is added
    showing all units side by side with independent CRF selectors.
    """
    if not series_list:
        raise ValueError("No series to render.")

    # ── Build hierarchies ─────────────────────────────────────────────────────
    # display_hier: plan → ep_key → dim → [series]  (only visible dimensions)
    # combined_hier: plan → ep_key → wl_unit → [series]  (for Combined tab)
    display_hier: dict = {}
    combined_hier: dict = {}

    for s in series_list:
        plan    = s.get("plan", "default")
        ep      = s.get("endpoint", "endpoint")
        alias   = s.get("alias") or None
        ep_key  = ep if not alias else f"{ep} [{alias}]"
        wl_unit = s.get("workload_unit")
        dim     = s["dimension"]

        # Hide "requests" dimensions derived from a workload — only show wl_unit dims
        if dim == "requests" and wl_unit:
            continue

        display_hier.setdefault(plan, {}).setdefault(ep_key, {}).setdefault(dim, []).append(s)
        if wl_unit:
            combined_hier.setdefault(plan, {}).setdefault(ep_key, {}).setdefault(wl_unit, []).append(s)

    plans = list(display_hier.keys())

    def _esc(s: str) -> str:
        return s.replace("'", "\\'").replace("/", "_").replace(" ", "_").replace("[", "_").replace("]", "_")

    def _fmt_limit(lim) -> str:
        period_str = format_time_with_unit(lim.period) if hasattr(lim.period, "to_milliseconds") else str(lim.period)
        return f"{lim.value:,} {lim.unit} / {period_str}"

    def _limits_panel(s: dict) -> str:
        rows = ""
        for r in s.get("rates", []):
            rows += f'<tr><td class="lk">rate</td><td class="lv">{_fmt_limit(r)}</td></tr>'
        for q in s.get("quotas", []):
            rows += f'<tr><td class="lk">quota</td><td class="lv">{_fmt_limit(q)}</td></tr>'
        if not rows:
            return ""
        return (
            '<div class="limits-panel">'
            '<div class="lp-title">Active limits</div>'
            f'<table><tbody>{rows}</tbody></table>'
            '</div>'
        )

    def _chart_div(s: dict) -> str:
        xs = [t / x_scale_divisor for t in s["t_ms"]]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=xs, y=s["capacity"],
            mode="lines",
            line=dict(color="green", shape=line_shape, width=1.5),
            fill="tozeroy", fillcolor="rgba(0, 128, 0, 0.2)",
            name="Capacity",
        ))
        crf_label = f"CRF = {s['crf']}" if s.get("crf") is not None else "fixed"
        fig.update_layout(
            title=dict(text=crf_label, font=dict(size=14)),
            xaxis_title=f"Time ({x_unit_label})",
            yaxis_title="Capacity",
            showlegend=False,
            template="plotly_white",
            autosize=True, height=460,
            margin=dict(t=60, b=60, l=70, r=30),
        )
        chart_html = fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})
        panel_html = _limits_panel(s)
        if panel_html:
            return (
                f'<div style="display:flex;align-items:flex-start;gap:12px">'
                f'<div style="flex-shrink:0;width:820px">{chart_html}</div>'
                f'{panel_html}</div>'
            )
        return f'<div style="max-width:860px">{chart_html}</div>'

    LEVEL_COLORS = ["#2e7d32", "#1565c0", "#6a1b9a", "#e65100"]
    _SCENARIO_PALETTE = [
        ("#d32f2f", "rgba(211,47,47,0.12)"),
        ("#f57c00", "rgba(245,124,0,0.12)"),
        ("#2e7d32", "rgba(46,125,50,0.15)"),
        ("#1565c0", "rgba(21,101,192,0.12)"),
        ("#6a1b9a", "rgba(106,27,154,0.12)"),
    ]

    def _combined_chart_div(series: list) -> str:
        fig = go.Figure()
        for idx, s in enumerate(series):
            lc, fc = _SCENARIO_PALETTE[idx % len(_SCENARIO_PALETTE)]
            crf_val = s.get("crf")
            trace_name = f"CRF = {crf_val}" if crf_val is not None else "fixed"
            xs = [t / x_scale_divisor for t in s["t_ms"]]
            fig.add_trace(go.Scatter(
                x=xs, y=s["capacity"],
                mode="lines", name=trace_name,
                line=dict(color=lc, shape=line_shape, width=2),
                fill="tozeroy", fillcolor=fc,
            ))
        fig.update_layout(
            title=dict(text="All scenarios", font=dict(size=14)),
            xaxis_title=f"Time ({x_unit_label})",
            yaxis_title="Capacity",
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            template="plotly_white",
            autosize=True, height=460,
            margin=dict(t=80, b=60, l=70, r=30),
        )
        html = fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})
        return f'<div style="max-width:860px">{html}</div>'

    def _btn(label: str, onclick: str, active: bool, level: int, extra_id: str = "") -> str:
        color = LEVEL_COLORS[min(level, 3)]
        active_style = f"font-weight:bold;border-bottom:3px solid {color};color:{color};"
        base_style   = ("margin:3px;padding:5px 14px;font-size:13px;cursor:pointer;"
                        "background:#fff;border:1px solid #ddd;border-radius:4px;transition:all .15s;")
        id_attr = f'id="{extra_id}"' if extra_id else ""
        return f'<button {id_attr} onclick="{onclick}" style="{base_style}{active_style if active else ""}">{label}</button>'

    def _crf_section(dim_id: str, series_for_dim: list) -> str:
        multi = len(series_for_dim) > 1
        if multi:
            overview_btn = _btn("Overview", f"showCrf('{dim_id}','ov')", True, 3,
                                extra_id=f"{dim_id}_crfbtn_ov")
            indiv_btns = "".join(
                _btn(
                    f"CRF = {s['crf']}" if s.get("crf") is not None else "fixed",
                    f"showCrf('{dim_id}',{ci})", False, 3,
                    extra_id=f"{dim_id}_crfbtn_{ci}",
                )
                for ci, s in enumerate(series_for_dim)
            )
            crf_nav = (
                f'<div class="nav-row"><div class="nav-label">Workload (CRF)</div>'
                f'{overview_btn}{indiv_btns}</div>'
            )
            overview_div = (
                f'<div id="{dim_id}_crf_ov" class="{dim_id}_crf" style="display:block">'
                f'{_combined_chart_div(series_for_dim)}</div>'
            )
            indiv_divs = "".join(
                f'<div id="{dim_id}_crf_{ci}" class="{dim_id}_crf" style="display:none">'
                f'{_chart_div(s)}</div>'
                for ci, s in enumerate(series_for_dim)
            )
            return crf_nav + overview_div + indiv_divs
        else:
            return (
                f'<div id="{dim_id}_crf_0" class="{dim_id}_crf" style="display:block">'
                f'{_chart_div(series_for_dim[0])}</div>'
            )

    def _combined_tab_section(ep_id: str, wl_units_dict: dict) -> str:
        """
        Single overlaid Plotly chart with all workload units.
        CRF selectors per unit toggle trace visibility via Plotly.restyle.
        """
        div_id = f"{ep_id}_comb_chart"
        fig = go.Figure()
        trace_idx = 0

        controls = '<div style="display:flex;flex-wrap:wrap;gap:16px;margin-bottom:4px">'
        for unit_i, (wl_unit, series) in enumerate(wl_units_dict.items()):
            unit_esc = _esc(wl_unit)
            unit_indices = list(range(trace_idx, trace_idx + len(series)))

            for ci, s in enumerate(series):
                lc, fc = _SCENARIO_PALETTE[(unit_i * 3 + ci) % len(_SCENARIO_PALETTE)]
                crf_val = s.get("crf")
                trace_name = f"{wl_unit} CRF={crf_val}" if crf_val is not None else wl_unit
                xs = [t / x_scale_divisor for t in s["t_ms"]]
                fig.add_trace(go.Scatter(
                    x=xs, y=s["capacity"],
                    mode="lines", name=trace_name,
                    line=dict(color=lc, shape=line_shape, width=2),
                    fill="tozeroy", fillcolor=fc,
                    visible=(ci == 0),
                ))
            trace_idx += len(series)

            if len(series) > 1:
                btns = "".join(
                    _btn(
                        f"CRF = {s['crf']}" if s.get("crf") is not None else "fixed",
                        f"showCombOverlay('{div_id}',{unit_indices},{ci},'{ep_id}','{unit_esc}')",
                        ci == 0, 3,
                        extra_id=f"comb_{ep_id}_{unit_esc}_btn_{ci}",
                    )
                    for ci, s in enumerate(series)
                )
                controls += (
                    f'<div class="nav-row" style="flex:none">'
                    f'<div class="nav-label">{wl_unit} — CRF</div>{btns}</div>'
                )
            else:
                controls += (
                    f'<div class="nav-row" style="flex:none">'
                    f'<div class="nav-label">{wl_unit} (fixed)</div></div>'
                )
        controls += '</div>'

        fig.update_layout(
            title=dict(text="Combined view", font=dict(size=14)),
            xaxis_title=f"Time ({x_unit_label})",
            yaxis_title="Capacity",
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            template="plotly_white",
            autosize=True, height=460,
            margin=dict(t=80, b=60, l=70, r=30),
        )
        chart_html = fig.to_html(
            full_html=False, include_plotlyjs=False,
            config={"responsive": True}, div_id=div_id,
        )
        return controls + f'<div style="max-width:860px">{chart_html}</div>'

    # ── HTML body generation ──────────────────────────────────────────────────
    body = ""
    for pi, plan in enumerate(plans):
        plan_id = f"plan_{_esc(plan)}"
        plan_display = "block" if pi == 0 else "none"
        eps = list(display_hier[plan].keys())

        ep_buttons = "".join(
            _btn(ep_key, f"showEp('{plan_id}','{_esc(ep_key)}')", i == 0, 1,
                 extra_id=f"{plan_id}_epbtn_{_esc(ep_key)}")
            for i, ep_key in enumerate(eps)
        )

        ep_sections = ""
        for ei, ep_key in enumerate(eps):
            ep_id = f"{plan_id}_ep_{_esc(ep_key)}"
            ep_display = "block" if ei == 0 else "none"
            dims = list(display_hier[plan][ep_key].keys())
            ep_combined = combined_hier.get(plan, {}).get(ep_key, {})
            has_combined = len(ep_combined) >= 2
            all_dim_tabs = dims + (["Combined"] if has_combined else [])

            dim_buttons = "".join(
                _btn(dim, f"showDim('{ep_id}','{_esc(dim)}')", i == 0, 2,
                     extra_id=f"{ep_id}_dimbtn_{_esc(dim)}")
                for i, dim in enumerate(all_dim_tabs)
            )

            dim_sections = ""
            for di, dim in enumerate(dims):
                dim_id = f"{ep_id}_dim_{_esc(dim)}"
                dim_display = "block" if di == 0 else "none"
                dim_sections += (
                    f'<div id="{dim_id}" class="{ep_id}_dim" style="display:{dim_display}">'
                    f'{_crf_section(dim_id, display_hier[plan][ep_key][dim])}</div>'
                )

            if has_combined:
                combined_dim_id = f"{ep_id}_dim_Combined"
                dim_sections += (
                    f'<div id="{combined_dim_id}" class="{ep_id}_dim" style="display:none">'
                    f'{_combined_tab_section(ep_id, ep_combined)}</div>'
                )

            ep_sections += (
                f'<div id="{ep_id}" class="{plan_id}_ep" style="display:{ep_display}">'
                f'<div class="nav-row"><div class="nav-label">Dimension</div>{dim_buttons}</div>'
                f'{dim_sections}</div>'
            )

        body += (
            f'<div id="{plan_id}" class="plan-section" style="display:{plan_display}">'
            f'<div class="nav-row"><div class="nav-label">Endpoint</div>{ep_buttons}</div>'
            f'{ep_sections}</div>'
        )

    plan_buttons = "".join(
        _btn(plan, f"showPlan('{_esc(plan)}')", i == 0, 0,
             extra_id=f"planbtn_{_esc(plan)}")
        for i, plan in enumerate(plans)
    )

    js = """
function _relayout() {
    document.querySelectorAll('.js-plotly-plot').forEach(function(el) {
        if (el.offsetParent !== null) { Plotly.Plots.resize(el); }
    });
}
function _updateBtns(prefix, activeKey, color) {
    document.querySelectorAll('[id^="' + prefix + '"]').forEach(function(btn) {
        var isActive = btn.id === prefix + activeKey;
        btn.style.fontWeight = isActive ? 'bold' : 'normal';
        btn.style.borderBottom = isActive ? '3px solid ' + color : 'none';
        btn.style.color = isActive ? color : '';
    });
}
function showPlan(planKey) {
    document.querySelectorAll('.plan-section').forEach(el => el.style.display = 'none');
    document.getElementById('plan_' + planKey).style.display = 'block';
    _updateBtns('planbtn_', planKey, '#2e7d32');
    _relayout();
}
function showEp(planId, epKey) {
    document.querySelectorAll('.' + planId + '_ep').forEach(el => el.style.display = 'none');
    document.getElementById(planId + '_ep_' + epKey).style.display = 'block';
    _updateBtns(planId + '_epbtn_', epKey, '#1565c0');
    _relayout();
}
function showDim(epId, dimKey) {
    document.querySelectorAll('.' + epId + '_dim').forEach(el => el.style.display = 'none');
    document.getElementById(epId + '_dim_' + dimKey).style.display = 'block';
    _updateBtns(epId + '_dimbtn_', dimKey, '#6a1b9a');
    _relayout();
}
function showCrf(dimId, key) {
    document.querySelectorAll('.' + dimId + '_crf').forEach(el => el.style.display = 'none');
    document.getElementById(dimId + '_crf_' + key).style.display = 'block';
    _updateBtns(dimId + '_crfbtn_', String(key), '#e65100');
    _relayout();
}
function showCombOverlay(divId, unitIndices, selectedIdx, epId, unitEsc) {
    var vis = unitIndices.map(function(_, ci) { return ci === selectedIdx; });
    Plotly.restyle(divId, {visible: vis}, unitIndices);
    _updateBtns('comb_' + epId + '_' + unitEsc + '_btn_', String(selectedIdx), '#e65100');
    _relayout();
}
"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body {{ font-family: sans-serif; margin: 0; padding: 16px; background: #fafafa; }}
    h2 {{ margin: 8px 0 14px; font-size: 20px; color: #222; }}
    .nav-row {{ margin: 4px 0 8px; padding: 6px 10px; background: #f0f0f0;
                border-radius: 6px; border-left: 3px solid #ccc; }}
    .nav-label {{ font-size: 10px; color: #999; font-weight: bold; letter-spacing: .8px;
                  text-transform: uppercase; margin-bottom: 4px; }}
    .limits-panel {{
      min-width: 190px; padding: 10px 14px; background: #fff;
      border: 1px solid #e0e0e0; border-radius: 6px; font-size: 12px;
      align-self: center;
    }}
    .lp-title {{ font-weight: bold; color: #555; margin-bottom: 8px;
                 font-size: 10px; text-transform: uppercase; letter-spacing: .8px; }}
    .limits-panel table {{ border-collapse: collapse; width: 100%; }}
    .limits-panel tr + tr td {{ padding-top: 5px; }}
    .lk {{ color: #999; padding-right: 10px; white-space: nowrap; vertical-align: top; font-size: 10px; text-transform: uppercase; }}
    .lv {{ color: #222; font-family: monospace; font-size: 12px; }}
  </style>
</head>
<body>
  <h2>{title}</h2>
  <div class="nav-row">
    <div class="nav-label">Plan</div>
    {plan_buttons}
  </div>
  {body}
  <script>{js}</script>
</body>
</html>"""


_PLAN_PALETTE = [
    ("#2e7d32", "rgba(46,125,50,0.15)"),
    ("#1565c0", "rgba(21,101,192,0.12)"),
    ("#6a1b9a", "rgba(106,27,154,0.12)"),
    ("#00838f", "rgba(0,131,143,0.12)"),
    ("#bf360c", "rgba(191,54,12,0.12)"),
]

_VERDICT_COLOR  = {"YES": "#2e7d32",                  "NO": "#c62828",                  "DEPENDS": "#f57c00"}
_VERDICT_FILL   = {"YES": "rgba(46,125,50,0.15)",      "NO": "rgba(198,40,40,0.12)",      "DEPENDS": "rgba(245,124,0,0.12)"}
_VERDICT_SYMBOL = {"YES": "✓",                         "NO": "✗",                         "DEPENDS": "?"}


def render_demand_evaluation_html(
    chart_data: dict,
    title: str,
    x_unit_label: str,
    x_scale_divisor: float,
) -> str:
    """
    Hierarchical navigation (Plan → Endpoint → Dimension) identical to render_multi_curve_html.
    Each dimension view shows plan capacity curve(s) + demand curve(s) coloured by per-plan verdict.

    chart_data structure:
      { plan: { ep_key: { dim: { "plan_curves": [...], "demand_curves": [...] } } } }

    plan_curve:   { label (CRF tag or None), t_ms, capacity }
    demand_curve: { label, verdict, reason, t_ms, capacity }
    """
    if not chart_data:
        raise ValueError("No chart data to render.")

    LEVEL_COLORS = ["#2e7d32", "#1565c0", "#6a1b9a", "#e65100"]

    def _esc(s: str) -> str:
        return s.replace("'", "\\'").replace("/", "_").replace(" ", "_").replace("[", "_").replace("]", "_")

    def _btn(label: str, onclick: str, active: bool, level: int, extra_id: str = "") -> str:
        color = LEVEL_COLORS[min(level, 3)]
        active_style = f"font-weight:bold;border-bottom:3px solid {color};color:{color};"
        base_style = ("margin:3px;padding:5px 14px;font-size:13px;cursor:pointer;"
                      "background:#fff;border:1px solid #ddd;border-radius:4px;transition:all .15s;")
        id_attr = f'id="{extra_id}"' if extra_id else ""
        return f'<button {id_attr} onclick="{onclick}" style="{base_style}{active_style if active else ""}">{label}</button>'

    def _scene_chart(scene: dict, plan_name: str, plan_idx: int) -> str:
        plan_curves   = scene["plan_curves"]
        demand_curves = scene["demand_curves"]
        fig = go.Figure()

        for i, s in enumerate(plan_curves):
            lc, fc = _PLAN_PALETTE[(plan_idx + i) % len(_PLAN_PALETTE)]
            xs = [t / x_scale_divisor for t in s["t_ms"]]
            crf_tag = f" — {s['label']}" if s.get("label") else ""
            name = f"{plan_name}{crf_tag}"
            fig.add_trace(go.Scatter(
                x=xs, y=s["capacity"], mode="lines", name=name,
                line=dict(color=lc, shape="linear", width=2),
                fill="tozeroy", fillcolor=fc,
            ))

        for s in demand_curves:
            verdict    = s.get("verdict", "DEPENDS")
            color      = _VERDICT_COLOR.get(verdict, "#888888")
            fill_color = _VERDICT_FILL.get(verdict, "rgba(136,136,136,0.12)")
            symbol     = _VERDICT_SYMBOL.get(verdict, "?")
            reason     = f" — {s['reason']}" if s.get("reason") else ""
            xs = [t / x_scale_divisor for t in s["t_ms"]]
            fig.add_trace(go.Scatter(
                x=xs, y=s["capacity"], mode="lines",
                name=f"{symbol} {s['label']}{reason}",
                line=dict(color=color, shape="linear", width=2),
                fill="tozeroy", fillcolor=fill_color,
            ))

        fig.update_layout(
            xaxis_title=f"Time ({x_unit_label})",
            yaxis_title="Capacity",
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            template="plotly_white",
            autosize=True, height=460,
            margin=dict(t=80, b=60, l=70, r=30),
        )
        html = fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})
        return f'<div style="max-width:900px">{html}</div>'

    plans = list(chart_data.keys())
    body  = ""

    for pi, plan in enumerate(plans):
        plan_id      = f"plan_{_esc(plan)}"
        plan_display = "block" if pi == 0 else "none"
        eps          = list(chart_data[plan].keys())

        ep_buttons = "".join(
            _btn(ep_key, f"showEp('{plan_id}','{_esc(ep_key)}')", i == 0, 1,
                 extra_id=f"{plan_id}_epbtn_{_esc(ep_key)}")
            for i, ep_key in enumerate(eps)
        )

        ep_sections = ""
        for ei, ep_key in enumerate(eps):
            ep_id      = f"{plan_id}_ep_{_esc(ep_key)}"
            ep_display = "block" if ei == 0 else "none"
            dims       = list(chart_data[plan][ep_key].keys())

            dim_buttons = "".join(
                _btn(dim, f"showDim('{ep_id}','{_esc(dim)}')", i == 0, 2,
                     extra_id=f"{ep_id}_dimbtn_{_esc(dim)}")
                for i, dim in enumerate(dims)
            )

            dim_sections = ""
            for di, dim in enumerate(dims):
                dim_id      = f"{ep_id}_dim_{_esc(dim)}"
                dim_display = "block" if di == 0 else "none"
                scene_html  = _scene_chart(chart_data[plan][ep_key][dim], plan_name=plan, plan_idx=pi)
                dim_sections += (
                    f'<div id="{dim_id}" class="{ep_id}_dim" style="display:{dim_display}">'
                    f'{scene_html}</div>'
                )

            ep_sections += (
                f'<div id="{ep_id}" class="{plan_id}_ep" style="display:{ep_display}">'
                + (f'<div class="nav-row"><div class="nav-label">Dimension</div>{dim_buttons}</div>'
                   if len(dims) > 1 else "")
                + f'{dim_sections}</div>'
            )

        body += (
            f'<div id="{plan_id}" class="plan-section" style="display:{plan_display}">'
            f'<div class="nav-row"><div class="nav-label">Endpoint</div>{ep_buttons}</div>'
            f'{ep_sections}</div>'
        )

    plan_buttons = "".join(
        _btn(plan, f"showPlan('{_esc(plan)}')", i == 0, 0,
             extra_id=f"planbtn_{_esc(plan)}")
        for i, plan in enumerate(plans)
    )

    js = """
function _relayout() {
    document.querySelectorAll('.js-plotly-plot').forEach(function(el) {
        if (el.offsetParent !== null) { Plotly.Plots.resize(el); }
    });
}
function _updateBtns(prefix, activeKey, color) {
    document.querySelectorAll('[id^="' + prefix + '"]').forEach(function(btn) {
        var isActive = btn.id === prefix + activeKey;
        btn.style.fontWeight = isActive ? 'bold' : 'normal';
        btn.style.borderBottom = isActive ? '3px solid ' + color : 'none';
        btn.style.color = isActive ? color : '';
    });
}
function showPlan(planKey) {
    document.querySelectorAll('.plan-section').forEach(el => el.style.display = 'none');
    document.getElementById('plan_' + planKey).style.display = 'block';
    _updateBtns('planbtn_', planKey, '#2e7d32');
    _relayout();
}
function showEp(planId, epKey) {
    document.querySelectorAll('.' + planId + '_ep').forEach(el => el.style.display = 'none');
    document.getElementById(planId + '_ep_' + epKey).style.display = 'block';
    _updateBtns(planId + '_epbtn_', epKey, '#1565c0');
    _relayout();
}
function showDim(epId, dimKey) {
    document.querySelectorAll('.' + epId + '_dim').forEach(el => el.style.display = 'none');
    document.getElementById(epId + '_dim_' + dimKey).style.display = 'block';
    _updateBtns(epId + '_dimbtn_', dimKey, '#6a1b9a');
    _relayout();
}
"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body {{ font-family: sans-serif; margin: 0; padding: 16px; background: #fafafa; }}
    h2 {{ margin: 8px 0 14px; font-size: 20px; color: #222; }}
    .nav-row {{ margin: 4px 0 8px; padding: 6px 10px; background: #f0f0f0;
                border-radius: 6px; border-left: 3px solid #ccc; }}
    .nav-label {{ font-size: 10px; color: #999; font-weight: bold; letter-spacing: .8px;
                  text-transform: uppercase; margin-bottom: 4px; }}
  </style>
</head>
<body>
  <h2>{title}</h2>
  <div class="nav-row">
    <div class="nav-label">Plan</div>
    {plan_buttons}
  </div>
  {body}
  <script>{js}</script>
</body>
</html>"""


def render_budget_recommendation_html(
    results: list,
    cost_curves: list,
    cap_time_curves: list,
    desired_capacity: float,
    capacity_unit: str,
    currency: str,
    max_budget: float | None,
) -> str:
    """
    Two Plotly charts + summary table.
    Chart 1: cost vs capacity (piecewise linear, breakpoints at quota values).
    Chart 2: capacity vs time (inflection-point curves) — same plan colors.
    Summary table below with budget_surplus column when max_budget is set.

    cost_curves:     list of {label, plan, xs, ys, quota_limit}
    cap_time_curves: list of {label, plan, t_ms, capacity, billing_period_ms}
    results:         list of recommendation dicts (for the table)
    """
    _COLOR_AFF  = "#2e7d32"
    _COLOR_NAFF = "#e65100"
    _COLOR_UNRC = "#9e9e9e"

    # ── shared color map (label → palette index) ──────────────────────────────
    color_map = {curve["label"]: i for i, curve in enumerate(cost_curves)}

    result_by_label = {
        (r["plan"] + (f" [{r['alias']}]" if r.get("alias") else "")): r
        for r in results
    }

    # ── Chart 1: cost vs capacity ─────────────────────────────────────────────
    fig1 = go.Figure()
    for i, curve in enumerate(cost_curves):
        lc, fc = _PLAN_PALETTE[i % len(_PLAN_PALETTE)]
        r = result_by_label.get(curve["label"])
        affordable = r["affordable"] if r else True
        unreachable = r["unreachable"] if r else False

        if unreachable:
            line_style = dict(color=_COLOR_UNRC, shape="linear", width=1.5, dash="dot")
            fill_color = "rgba(158,158,158,0.08)"
        elif not affordable:
            line_style = dict(color=_COLOR_NAFF, shape="linear", width=2)
            fill_color = "rgba(230,81,0,0.10)"
        else:
            line_style = dict(color=lc, shape="linear", width=2)
            fill_color = fc

        fig1.add_trace(go.Scatter(
            x=curve["xs"], y=curve["ys"],
            mode="lines", name=curve["label"],
            line=line_style, fill="tozeroy", fillcolor=fill_color,
            hovertemplate=(
                f"<b>{curve['label']}</b><br>"
                f"Capacity: %{{x:,.0f}} {capacity_unit}<br>"
                f"Cost: %{{y:.2f}} {currency}<extra></extra>"
            ),
        ))

    fig1.add_vline(
        x=desired_capacity,
        line=dict(color="#37474f", dash="dash", width=1.5),
        annotation_text=f"Target: {desired_capacity:g} {capacity_unit}",
        annotation_position="top right", annotation_font_size=11,
    )
    if max_budget is not None:
        fig1.add_hline(
            y=max_budget,
            line=dict(color="#c62828", dash="dash", width=1.5),
            annotation_text=f"Budget: {max_budget} {currency}",
            annotation_position="bottom right", annotation_font_size=11,
        )

    fig1.update_layout(
        xaxis_title=f"Capacity ({capacity_unit})",
        yaxis_title=f"Total cost ({currency})",
        template="plotly_white", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        autosize=True, height=460, margin=dict(t=80, b=60, l=80, r=30),
    )
    chart1_html = fig1.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})

    # ── Chart 2: capacity vs time ─────────────────────────────────────────────
    chart2_html = ""
    if cap_time_curves:
        max_t = max(max(c["t_ms"]) for c in cap_time_curves if c["t_ms"])
        best = select_best_time_unit(max_t)
        t_div = best.unit.to_milliseconds()
        t_label = best.unit.value

        fig2 = go.Figure()
        for curve in cap_time_curves:
            idx = color_map.get(curve["label"], 0)
            lc, fc = _PLAN_PALETTE[idx % len(_PLAN_PALETTE)]
            r = result_by_label.get(curve["label"])
            unreachable = r["unreachable"] if r else False
            affordable = r["affordable"] if r else True

            if unreachable:
                line_style = dict(color=_COLOR_UNRC, shape="linear", width=1.5, dash="dot")
                fill_color = "rgba(158,158,158,0.08)"
            elif not affordable:
                line_style = dict(color=_COLOR_NAFF, shape="linear", width=2)
                fill_color = "rgba(230,81,0,0.10)"
            else:
                line_style = dict(color=lc, shape="linear", width=2)
                fill_color = fc

            xs = [t / t_div for t in curve["t_ms"]]
            fig2.add_trace(go.Scatter(
                x=xs, y=curve["capacity"],
                mode="lines", name=curve["label"],
                line=line_style, fill="tozeroy", fillcolor=fill_color,
                hovertemplate=(
                    f"<b>{curve['label']}</b><br>"
                    f"Time: %{{x:.2f}} {t_label}<br>"
                    f"Capacity: %{{y:,.0f}} {capacity_unit}<extra></extra>"
                ),
            ))

        fig2.add_hline(
            y=desired_capacity,
            line=dict(color="#37474f", dash="dash", width=1.5),
            annotation_text=f"Target: {desired_capacity:g} {capacity_unit}",
            annotation_position="top right", annotation_font_size=11,
        )
        fig2.update_layout(
            xaxis_title=f"Time ({t_label})",
            yaxis_title=f"Capacity ({capacity_unit})",
            template="plotly_white", showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            autosize=True, height=460, margin=dict(t=80, b=60, l=80, r=30),
        )
        chart2_html = fig2.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})

    budget_tag = f" | budget: {max_budget} {currency}" if max_budget is not None else ""
    title = f"Plan Recommendation — {desired_capacity:g} {capacity_unit}{budget_tag}"

    # ── summary table ─────────────────────────────────────────────────────────
    show_surplus = max_budget is not None
    reachable_rows   = [r for r in results if not r["unreachable"]]
    unreachable_rows = [r for r in results if r["unreachable"]]

    def _tr(r, faded=False):
        t = r.get("time_to_capacity") or "—"
        aff = "✓" if r["affordable"] else "✗"
        aff_color = _COLOR_AFF if r["affordable"] else _COLOR_NAFF
        unrc_text = f"⚠ {r['unreachable_reason'] or 'unreachable'}" if r["unreachable"] else ""
        alias = f" [{r['alias']}]" if r.get("alias") else ""
        row_style = "color:#aaa" if faded else ""
        overage_style = "color:#c62828" if r["overage_cost"] > 0 else ""
        surplus = r.get("budget_surplus")
        surplus_cell = (
            f'<td style="text-align:right;color:{_COLOR_AFF}">{surplus:.2f}</td>'
            if surplus is not None else '<td style="text-align:right;color:#aaa">—</td>'
        ) if show_surplus else ""
        return (
            f'<tr style="{row_style}">'
            f'<td><b>{r["plan"]}{alias}</b></td>'
            f'<td>{r["endpoint"]}</td>'
            f'<td>{r["dimension"]}</td>'
            f'<td style="text-align:right">{r["base_cost"]:.2f}</td>'
            f'<td style="text-align:right;{overage_style}">{r["overage_cost"]:.4f}</td>'
            f'<td style="text-align:right"><b>{r["total_cost"]:.2f}</b></td>'
            f'<td style="color:{aff_color};font-weight:bold;text-align:center">{aff}</td>'
            f'{surplus_cell}'
            f'<td>{t}</td>'
            f'<td style="color:{_COLOR_UNRC};font-size:11px">{unrc_text}</td>'
            f'</tr>'
        )

    surplus_th = f'<th style="padding:6px 10px;text-align:right">Surplus ({currency})</th>' if show_surplus else ""
    rows = "".join(_tr(r) for r in reachable_rows) + "".join(_tr(r, faded=True) for r in unreachable_rows)

    table = f"""
<table style="border-collapse:collapse;width:100%;font-size:13px;margin-top:20px">
  <thead>
    <tr style="background:#f0f0f0;text-align:left">
      <th style="padding:6px 10px">Plan</th>
      <th style="padding:6px 10px">Endpoint</th>
      <th style="padding:6px 10px">Dimension</th>
      <th style="padding:6px 10px;text-align:right">Base ({currency})</th>
      <th style="padding:6px 10px;text-align:right">Overage ({currency})</th>
      <th style="padding:6px 10px;text-align:right">Total ({currency})</th>
      <th style="padding:6px 10px;text-align:center">Affordable</th>
      {surplus_th}
      <th style="padding:6px 10px">Time to {desired_capacity:g} {capacity_unit}</th>
      <th style="padding:6px 10px">Notes</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""

    cap_section = (
        f'<h3 style="margin:24px 0 6px;font-size:16px;color:#444">Capacity vs Time (billing period)</h3>'
        f'<div style="max-width:960px">{chart2_html}</div>'
        if chart2_html else ""
    )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body {{ font-family: sans-serif; margin: 0; padding: 16px; background: #fafafa; }}
    h2 {{ margin: 8px 0 14px; font-size: 20px; color: #222; }}
    table td, table th {{ border: 1px solid #e0e0e0; padding: 5px 10px; }}
    table tbody tr:hover td {{ background: #f5f5f5; }}
  </style>
</head>
<body>
  <h2>{title}</h2>
  <h3 style="margin:8px 0 6px;font-size:16px;color:#444">Cost vs Capacity</h3>
  <div style="max-width:960px">{chart1_html}</div>
  {cap_section}
  {table}
</body>
</html>"""


if __name__ == "__main__":
    import os
    import webbrowser
    from app.models import Rate, Quota
    from app.engine.evaluators.bounded_rate import BoundedRate
    from app.engine.plotters.bounded_rate_plotter import BoundedRatePlotter
    from app.utils.time_utils import parse_time_string_to_duration

    # User's configuration
    rate = Rate(value=120*70, unit="emails", period="1min")
    quota = Quota(value=50000, unit="emails", period="1month")
    quota_2 = Quota(value=100000*70, unit="emails", period="1day")
    bounded_rate = BoundedRate(rate=rate, quota=[quota, quota_2])

    workload = "1, 70 EMAILS  -> " 
    # Time simulation length
    time_sim = "3day"

    print("Generating points with BoundedRatePlotter...")
    plotter = BoundedRatePlotter(br=bounded_rate)
    
    # "show_capacity_from_inflection_points" corresponds to inflection_point_capacity_curve
    points = plotter.accumulated_capacity_curve(time_sim)

    # Automatically select a good unit for the x-axis divisor
    # Let's just use 'day' for a 2 month simulation for simplicity
    x_unit_label = "day"
    x_scale_divisor = 86400000.0  # ms in a day

    html = render_capacity_curve_html(
        points=points,
        title=f"Capacity Curve from Inflection Points ({time_sim})",
        line_shape="hv",
        x_unit_label=x_unit_label,
        x_scale_divisor=x_scale_divisor
    )

    output_path = os.path.abspath("test_plot_output.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"Plot saved to {output_path}")
    webbrowser.open(f"file://{output_path}")
