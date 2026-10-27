/** SeatStrip: one cell per seat. Green = occupied within intake, outlined = vacant, red = over intake,
 *  dark bar = approved-intake line. Below, one strip per supernumerary category (amber, red over cap). */

export type Position = {
  approved_intake: number;
  within_intake_enrolled: number;
  excess_over_intake: number;
  supernumerary: Record<string, { enrolled: number; cap: number; excess: number }>;
  utilisation_pct?: number | null;
};

const CELL = 10;
const GAP = 2;
const PER_ROW = 60;
const LABELS: Record<string, string> = { SN_FN_OCI: "FN/OCI", SN_CIWG: "CIWG", SN_TFW: "TFW", SN_OTHER: "Other" };

type Cell = { fill: string; stroke: string };

function Cells({ cells, intakeLine, label }: { cells: Cell[]; intakeLine?: number; label: string }) {
  const n = Math.max(cells.length, 1);
  const cols = Math.min(n, PER_ROW);
  const rows = Math.ceil(n / PER_ROW);
  const w = cols * (CELL + GAP) + 4;
  const h = rows * (CELL + GAP) + 2;
  let line: { x: number; y: number } | null = null;
  if (intakeLine !== undefined && intakeLine > 0) {
    const idx = intakeLine - 1;
    line = { x: (idx % PER_ROW) * (CELL + GAP) + CELL + 1, y: Math.floor(idx / PER_ROW) * (CELL + GAP) };
  }
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label}>
      {cells.map((c, i) => (
        <rect key={i} x={(i % PER_ROW) * (CELL + GAP) + 0.5} y={Math.floor(i / PER_ROW) * (CELL + GAP) + 0.5}
          width={CELL - 1} height={CELL - 1} rx={2} fill={c.fill} stroke={c.stroke} strokeWidth={1} />
      ))}
      {line && <rect x={line.x - 0.5} y={line.y - 1} width={2.5} height={CELL + 2} fill="#1b2a41" />}
    </svg>
  );
}

export default function SeatStrip({ pos, compact = false }: { pos: Position; compact?: boolean }) {
  const intake = pos.approved_intake;
  const within = pos.within_intake_enrolled;
  const total = Math.max(intake, within);
  const main: Cell[] = [];
  for (let i = 0; i < total; i++) {
    if (i < Math.min(within, intake)) main.push({ fill: "#0f6e5c", stroke: "#0f6e5c" });
    else if (i < intake) main.push({ fill: "#ffffff", stroke: "#8fa39d" });
    else main.push({ fill: "#b42318", stroke: "#b42318" });
  }
  const label = `${within} of ${intake} approved seats occupied` + (pos.excess_over_intake ? `, ${pos.excess_over_intake} over intake` : "");
  const cats = Object.entries(pos.supernumerary || {}).filter(([, v]) => v.cap > 0 || v.enrolled > 0);
  return (
    <div className="seatstrip">
      <Cells cells={main} intakeLine={intake} label={label} />
      <div className="cap">
        Within intake {within}/{intake}
        {pos.excess_over_intake > 0 && <strong style={{ color: "var(--red)" }}> · +{pos.excess_over_intake} over intake</strong>}
      </div>
      {!compact && (
        <div className="sn-row">
          {cats.map(([cat, v]) => {
          const cells: Cell[] = [];
          for (let i = 0; i < Math.max(v.cap, v.enrolled); i++) {
            if (i < Math.min(v.enrolled, v.cap)) cells.push({ fill: "#a8650f", stroke: "#a8650f" });
            else if (i < v.cap) cells.push({ fill: "#ffffff", stroke: "#d2a96b" });
            else cells.push({ fill: "#b42318", stroke: "#b42318" });
          }
          return (
            <div key={cat}>
              <Cells cells={cells} label={`Supernumerary ${LABELS[cat]} ${v.enrolled} of ${v.cap}`} />
              <div className="cap">
                Supernumerary {LABELS[cat] || cat} {v.enrolled}/{v.cap}
                {v.excess > 0 && <strong style={{ color: "var(--red)" }}> · +{v.excess} over cap</strong>}
              </div>
            </div>
          );
          })}
        </div>
      )}
    </div>
  );
}

export function SeatLegend() {
  return (
    <div className="legend" aria-hidden>
      <span><i style={{ background: "#0f6e5c" }} />Occupied within intake</span>
      <span><i style={{ background: "#fff", border: "1px solid #8fa39d" }} />Vacant</span>
      <span><i style={{ background: "#b42318" }} />Over intake / cap</span>
      <span><i style={{ background: "#a8650f" }} />Supernumerary</span>
      <span><i style={{ background: "#1b2a41", width: 3 }} />Approved intake line</span>
    </div>
  );
}
