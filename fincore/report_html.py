"""Render a month_report dict as one self-contained, phone-friendly HTML page.
No external scripts or fonts; bars are plain HTML so they work offline."""
from datetime import date
from html import escape

from fincore.money import format_amount

CSS = """
:root{color-scheme:light;--bg:#f4f3ef;--surface:#fcfcfb;--line:#e4e2dc;--text:#0b0b0b;--muted:#52514e;
--faint:#8a8984;--s1:#2a78d6;--s2:#eb6834;--track:#ecebe6;--good:#0ca30c;--warn:#b07a00;--crit:#d03b3b;
--good-bg:#e6f5e6;--crit-bg:#fbe9e9;--warn-bg:#fdf3dc}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;
--surface:#1a1a19;--line:#2f2f2c;--text:#f0efec;--muted:#c3c2b7;--faint:#8f8e86;--s1:#3987e5;--s2:#d95926;
--track:#2a2a27;--good:#0ca30c;--warn:#fab219;--crit:#e66767;--good-bg:#16301a;--crit-bg:#3a1c1c;--warn-bg:#3a2f12}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--line:#2f2f2c;--text:#f0efec;
--muted:#c3c2b7;--faint:#8f8e86;--s1:#3987e5;--s2:#d95926;--track:#2a2a27;--good:#0ca30c;--warn:#fab219;
--crit:#e66767;--good-bg:#16301a;--crit-bg:#3a1c1c;--warn-bg:#3a2f12}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:720px;margin:0 auto;padding:16px 16px 48px}
h1{font-size:22px;margin:4px 0 2px}
.sub{color:var(--muted);font-size:13px;margin:0 0 16px}
section{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px;margin:0 0 14px}
h2{font-size:16px;margin:0 0 4px}
.note{color:var(--muted);font-size:12.5px;margin:0 0 12px}
table.card{width:100%;border-collapse:collapse}
table.card td{padding:9px 4px;border-top:1px solid var(--line)}
table.card tr:first-child td{border-top:0}
table.card td.v{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.pill{display:inline-block;font-size:11.5px;font-weight:600;padding:1px 7px;border-radius:99px;margin-left:6px;vertical-align:1px}
.pill.good{background:var(--good-bg);color:var(--good)}.pill.crit{background:var(--crit-bg);color:var(--crit)}
.pill.warn{background:var(--warn-bg);color:var(--warn)}
.row{display:grid;grid-template-columns:minmax(0,44%) 1fr auto;gap:8px;align-items:center;padding:5px 0}
.row .lab{font-size:13px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .val{font-size:13px;font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.track{position:relative;height:12px;background:var(--track);border-radius:4px}
.fill{position:absolute;left:0;top:0;bottom:0;border-radius:0 4px 4px 0;background:var(--s1)}
.fill.alt{background:var(--s2)}.fill.over{background:var(--crit)}.fill.near{background:var(--warn)}
.limit{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--text);opacity:.55}
.legend{display:flex;gap:14px;font-size:12.5px;color:var(--muted);margin:0 0 8px;flex-wrap:wrap}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.pair{display:grid;grid-template-columns:64px 1fr;gap:8px;align-items:center;padding:4px 0}
.pair .lab{font-size:12.5px;color:var(--muted)}
.pair .bars{display:flex;flex-direction:column;gap:2px}
.mini{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center}
.mini .track{height:9px}.mini .val{font-size:12px;font-variant-numeric:tabular-nums;color:var(--muted);min-width:88px;text-align:right}
.stack{display:flex;height:12px;border-radius:4px;overflow:hidden;background:var(--track);gap:2px}
.stack span{display:block;height:100%}
.list{width:100%;border-collapse:collapse;font-size:13px}
.list th{font-weight:600;color:var(--muted);text-align:left;padding:6px 4px;border-bottom:1px solid var(--line)}
.list td{padding:6px 4px;border-bottom:1px solid var(--line)}.list td.n,.list th.n{text-align:right;font-variant-numeric:tabular-nums}
.period{margin-top:12px}.period h3{font-size:14px;margin:0 0 4px}
details{margin-top:8px}summary{cursor:pointer;color:var(--muted);font-size:12.5px}
#tip{position:fixed;pointer-events:none;background:var(--text);color:var(--surface);font-size:12px;padding:5px 8px;
border-radius:6px;opacity:0;transition:opacity .1s;z-index:9;max-width:240px}
"""

JS = """
const tip=document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el=>{
 const show=e=>{tip.textContent=el.dataset.tip;tip.style.opacity=1;
  const p=e.touches?e.touches[0]:e;tip.style.left=Math.min(p.clientX+12,innerWidth-250)+'px';tip.style.top=(p.clientY+14)+'px'};
 el.addEventListener('mousemove',show);el.addEventListener('touchstart',show,{passive:true});
 el.addEventListener('mouseleave',()=>tip.style.opacity=0);});
document.addEventListener('touchstart',e=>{if(!e.target.closest('[data-tip]'))tip.style.opacity=0},{passive:true});
"""


def _m(c) -> str:
    return "—" if c is None else format_amount(c)


def _pct(part: int, whole: int) -> float:
    return 0.0 if whole <= 0 else max(0.0, min(100.0, 100.0 * part / whole))


def _bar_row(label: str, amount: int, scale: int, cls: str = "", tip: str = "") -> str:
    return (f'<div class="row" data-tip="{escape(tip or label + ": " + _m(amount))}">'
            f'<span class="lab">{escape(label)}</span>'
            f'<span class="track"><span class="fill {cls}" style="width:{_pct(amount, scale):.1f}%"></span></span>'
            f'<span class="val">{_m(amount)}</span></div>')


def _summary(r: dict) -> str:
    s = r["summary"]

    def pill(ok: bool, good: str, bad: str) -> str:
        return f'<span class="pill {"good" if ok else "crit"}">{good if ok else bad}</span>'

    rows = [
        ("Total income", s["income"], ""),
        ("Total expenses", s["expenses"], ""),
        ("Income − expenses", s["net"], pill(s["net"] >= 0, "surplus", "deficit")),
        ("Savings goal", s["savings_goal"], ""),
        ("Actual savings", s["savings_actual"],
         pill(s["savings_actual"] >= s["savings_goal"], "on track", "below goal") if s["savings_goal"] else ""),
        ("Debt payment goal", s["debt_goal"], ""),
        ("Actual debt paid", s["debt_paid"],
         pill(s["debt_paid"] >= s["debt_goal"], "paid", "still due") if s["debt_goal"] else ""),
        ("Money left this month", r["money_left"], ""),
    ]
    body = "".join(f"<tr><td>{escape(n)}{p}</td><td class='v'>{_m(v)}</td></tr>" for n, v, p in rows)
    bills = "".join(f"<li>{escape(b['name'])}: {_m(b['amount'])} due {_d(b['due'])}</li>" for b in r["debt_bills"])
    extra = f"<p class='note' style='margin:10px 0 0'>Card bills this month:</p><ul class='note'>{bills}</ul>" if bills else ""
    return (f"<section><h2>{escape(r['month'].upper())}</h2>"
            f"<table class='card'>{body}</table>{extra}</section>")


def _d(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _spending(r: dict) -> str:
    rows = r["spend_by_category"]
    if not rows:
        return "<section><h2>Where the money went</h2><p class='note'>No spending logged this month yet.</p></section>"
    top = rows[0]["amount"]
    bars = "".join(_bar_row(x["category"], x["amount"], top) for x in rows)
    return (f"<section><h2>Where the money went</h2>"
            f"<p class='note'>Spending by category this month, incl. card installment charges billed this month.</p>"
            f"{bars}</section>")


def _budgets(r: dict) -> str:
    out = []
    for p in r["periods"]:
        cats = [c for c in p["categories"] if c["limit"] is not None or c["spent"]]
        if not cats:
            continue
        scale = max(max(c["spent"], c["limit"] or 0) for c in cats)
        rows = []
        for c in sorted(cats, key=lambda c: -(c["ratio"] or 0)):
            lvl = {"over": "over", "near": "near"}.get(c["level"], "")
            lim = c["limit"]
            if lim is None:
                tail, tip = _m(c["spent"]), f"{c['category']}: {_m(c['spent'])} (no limit)"
            elif c["level"] == "over":
                tail, tip = f"over {_m(c['spent'] - lim)}", f"{c['category']}: {_m(c['spent'])} of {_m(lim)}"
            else:
                tail, tip = f"{_m(lim - c['spent'])} left", f"{c['category']}: {_m(c['spent'])} of {_m(lim)}"
            marker = f'<span class="limit" style="left:{_pct(lim, scale):.1f}%"></span>' if lim else ""
            rows.append(f'<div class="row" data-tip="{escape(tip)}"><span class="lab">{escape(c["category"])}</span>'
                        f'<span class="track"><span class="fill {lvl}" style="width:{_pct(c["spent"], scale):.1f}%">'
                        f'</span>{marker}</span><span class="val">{escape(tail)}</span></div>')
        out.append(f"<div class='period'><h3>Pay period {escape(p['label'])}</h3>{''.join(rows)}</div>")
    if not out:
        return ""
    return ("<section><h2>Budget vs limit</h2><p class='note'>Bar = spent, line = limit. "
            "Red = over, amber = 80% or more.</p>" + "".join(out) + "</section>")


def _trend(r: dict) -> str:
    t = r["trend"]
    scale = max([max(x["income"], x["expenses"]) for x in t] + [1])
    rows = "".join(
        f'<div class="pair"><span class="lab">{escape(x["month"])}</span><div class="bars">'
        f'<div class="mini" data-tip="{escape(x["month"])} income: {_m(x["income"])}"><span class="track">'
        f'<span class="fill" style="width:{_pct(x["income"], scale):.1f}%"></span></span><span class="val">{_m(x["income"])}</span></div>'
        f'<div class="mini" data-tip="{escape(x["month"])} expenses: {_m(x["expenses"])}"><span class="track">'
        f'<span class="fill alt" style="width:{_pct(x["expenses"], scale):.1f}%"></span></span><span class="val">{_m(x["expenses"])}</span></div>'
        f'</div></div>' for x in t)
    return ("<section><h2>Income vs expenses</h2><p class='note'>Last 6 months. Months before you started tracking show ₱0.</p>"
            "<div class='legend'><span><i style='background:var(--s1)'></i>Income</span>"
            "<span><i style='background:var(--s2)'></i>Expenses</span></div>" + rows + "</section>")


def _debts(r: dict) -> str:
    ds = r["debts"]
    if not ds:
        return ""
    scale = max(d["owed"] + d["installments_left"] for d in ds) or 1
    rows = []
    for d in ds:
        due = f" · due {_d(d['next_due'])}" if d["next_due"] else ""
        rows.append(
            f'<div style="padding:6px 0" data-tip="{escape(d["name"])}: {_m(d["owed"])} balance + '
            f'{_m(d["installments_left"])} installments not yet billed">'
            f'<div style="display:flex;justify-content:space-between;font-size:13px"><span>{escape(d["name"])}'
            f'<span class="note">{escape(due)}</span></span><b>{_m(d["owed"] + d["installments_left"])}</b></div>'
            f'<div class="stack" style="width:{_pct(d["owed"] + d["installments_left"], scale):.1f}%">'
            f'<span style="flex:{max(d["owed"], 0)};background:var(--s1)"></span>'
            f'<span style="flex:{d["installments_left"]};background:var(--s2)"></span></div></div>')
    inst = "".join(f"<tr><td>{escape(i['item'])}<br><span class='note'>{escape(i['card'])}</span></td>"
                   f"<td class='n'>{_m(i['monthly'])}</td><td class='n'>{i['left']}</td>"
                   f"<td class='n'>{_d(i['last'])}</td></tr>" for i in r["installments"])
    table = (f"<details><summary>Installments ({len(r['installments'])})</summary><table class='list'>"
             f"<tr><th>Plan</th><th class='n'>Monthly</th><th class='n'>Left</th><th class='n'>Last charge</th></tr>"
             f"{inst}</table></details>") if inst else ""
    return (f"<section><h2>What you owe: {_m(r['debt_total'])}</h2>"
            "<div class='legend'><span><i style='background:var(--s1)'></i>Current balance</span>"
            "<span><i style='background:var(--s2)'></i>Installments not yet billed</span></div>"
            + "".join(rows) + table + "</section>")


def _owed(r: dict) -> str:
    ps = r["owed_to_you"]
    if not ps:
        return ""
    top = ps[0]["owed"]
    return (f"<section><h2>Owed to you: {_m(r['owed_to_you_total'])}</h2>"
            + "".join(_bar_row(p["name"], p["owed"], top) for p in ps) + "</section>")


def _goals(r: dict) -> str:
    rows = []
    for g in r["goals"]:
        if g["target"]:
            label = f"{_m(g['saved'])} of {_m(g['target'])}"
            width = _pct(g["saved"], g["target"])
        else:
            label, width = f"{_m(g['saved'])} · target set after 2 pay periods", 0
        plan = f"{_m(g['planned'])} per pay period" if g["planned"] else "no amount per pay period yet"
        rows.append(f'<div style="padding:6px 0" data-tip="{escape(g["name"])}: {escape(label)}">'
                    f'<div style="display:flex;justify-content:space-between;font-size:13px">'
                    f'<span>{escape(g["name"])}</span><b>{escape(label)}</b></div>'
                    f'<div class="track" style="margin:5px 0 2px"><span class="fill" style="width:{width:.1f}%"></span></div>'
                    f'<span class="note">{escape(plan)}</span></div>')
    return "<section><h2>Savings goals</h2>" + "".join(rows) + "</section>" if rows else ""


def _balances(r: dict) -> str:
    spend = [b for b in r["balances"] if b["role"] == "spending"]
    save = [b for b in r["balances"] if b["role"] == "savings"]
    if not spend and not save:
        return ""
    rows = lambda bs: "".join(f"<tr><td>{escape(b['name'])}</td><td class='n'>{_m(b['balance'])}</td></tr>"
                              for b in bs)
    out = (f"<section><h2>Money you can use: {_m(sum(b['balance'] for b in spend))}</h2>"
           "<p class='note'>What's in your spending accounts today. Savings aren't counted here. "
           "Money left this month = what came into these accounts minus what went out "
           "(spending, card payments and money moved to savings).</p>"
           f"<table class='list'>{rows(spend)}</table>")
    asides = r.get("set_asides") or []
    if asides:
        out += (f"<p class='note' style='margin:12px 0 4px'>Set aside from this money: "
                f"{_m(sum(x['amount'] for x in asides))}</p><table class='list'>"
                + "".join(f"<tr><td>{escape(x['name'])}</td><td class='n'>{_m(x['amount'])}</td></tr>" for x in asides)
                + "</table>")
    if save:
        out += (f"<p class='note' style='margin:12px 0 4px'>Savings (not counted above): "
                f"{_m(sum(b['balance'] for b in save))}</p><table class='list'>{rows(save)}</table>")
    return out + "</section>"


STATUS_PILL = {"paid": "good", "moved": "good", "partly paid": "warn", "partly moved": "warn",
               "due": "warn", "not yet moved": "crit", "overdue": "crit", "upcoming": "", "no amount set": ""}


def _pill(status: str) -> str:
    return f'<span class="pill {STATUS_PILL.get(status, "")}">{escape(status)}</span>'


def _to_pay(r: dict) -> str:
    items = r["to_pay"]
    if not items:
        return ""
    rows = "".join(
        f"<tr><td>{_d(x['due'])}</td><td>{escape(x['name'])}{_pill(x['status'])}"
        + (f"<br><span class='note'>paid {_m(x['paid'])}</span>" if x["paid"] and x["status"] != "paid" else "")
        + f"</td><td class='n'>{_m(x['expected'])}</td></tr>" for x in items)
    open_items = [x for x in items if x["status"] != "paid"]
    head = (f"{len(open_items)} of {len(items)} still to pay" if open_items else "Everything this month is paid")
    return (f"<section><h2>To pay this month</h2><p class='note'>{escape(head)}. Card bills include "
            f"subscriptions and installments charged to the card.</p><table class='list'>"
            f"<tr><th>Due</th><th>Bill</th><th class='n'>Amount</th></tr>{rows}</table></section>")


def _savings(r: dict) -> str:
    items = r["savings_moves"]
    if not items:
        return ""
    rows = "".join(
        f"<tr><td>{escape(x['goal'])}{_pill(x['status'])}</td>"
        f"<td>{escape(x['period'] or '—')}</td>"
        f"<td class='n'>{_m(x['moved']) if x['planned'] else '—'}"
        + (f" / {_m(x['planned'])}" if x["planned"] else "") + "</td></tr>" for x in items)
    return ("<section><h2>Savings to move</h2><p class='note'>Planned savings per pay period and whether "
            "it has gone to savings yet. Money moved up to 5 days before payday counts for that payday.</p>"
            f"<table class='list'><tr><th>Goal</th><th>Pay period</th><th class='n'>Moved / planned</th></tr>"
            f"{rows}</table></section>")


def _flow_table(rows: list[dict]) -> str:
    body = "".join(
        f"<tr><td>{_d(x['date'])}</td><td>{escape(x['what'])}<br><span class='note'>{escape(x['category'])}"
        f" · {escape(x['account'])}{(' · ' + escape(x['note'])) if x['note'] else ''}</span></td>"
        f"<td class='n'>{_m(x['amount'])}</td></tr>" for x in rows)
    return f"<table class='list'><tr><th>Date</th><th>What</th><th class='n'>Amount</th></tr>{body}</table>"


def _flows(r: dict) -> str:
    ins, outs = r["inflows"], r["outflows"]
    return ("<section><h2>Money in and out</h2>"
            f"<details><summary>Money in ({len(ins)}) · {_m(sum(x['amount'] for x in ins))}</summary>"
            f"{_flow_table(ins) if ins else '<p class=note>Nothing yet.</p>'}</details>"
            f"<details><summary>Money out ({len(outs)}) · {_m(sum(x['amount'] for x in outs))}</summary>"
            f"{_flow_table(outs) if outs else '<p class=note>Nothing yet.</p>'}</details></section>")


def render(r: dict) -> str:
    today = date.fromisoformat(r["today"])
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Money Tracker</title><style>{CSS}</style></head><body><main>"
            f"<h1>Money tracker</h1><p class='sub'>{escape(r['month'])} · as of {today:%b} {today.day}, {today.year}</p>"
            + _summary(r) + _balances(r) + _to_pay(r) + _savings(r) + _flows(r) + _spending(r) + _budgets(r) + _debts(r) + _owed(r) + _goals(r) + _trend(r)
            + f"</main><div id='tip'></div><script>{JS}</script></body></html>")
