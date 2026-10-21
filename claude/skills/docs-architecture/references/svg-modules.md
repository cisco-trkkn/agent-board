# SVG modules

Copy-ready pieces for the Docs diagram widget. Render coverage with the token prelude (residual fix, scratch Doc, deleted after): the composed example below, a sheet of all 22 glyph helpers in labelled nodes, and a primitive sheet (org, project, VPC and subnet boundaries nested, dev and stage bands, a swimlane, the three edge styles and the marker). Both sheets and the example published with `diagnostics: []`; light via the Docs screenshot read (`errors: []`), dark via Chrome on the Doc (the viewer's own dark theme, all 22 glyphs and the primitives legible). Pictures: `.superpowers/sdd/2026-10-20-docs-architecture-skill/residual-{glyphs,primitives}-{light.png,dark.jpg}`. The widget contract is `anthropic-skills:docs` → `guide(["topic.diagram"])`: one module, `export default () => { consts; lowercase helpers; return <svg viewBox='0 0 760 H' role='img' aria-label='<title>'>…</svg>; }`, sent as ONE line with single quotes inside, in a `batch` of two members (widget `create`, then the prose `update` whose embed points at it). Read that topic first; this file adds what the render check taught.

What the validator refuses, learned by refusal (each stages the module with errors, nothing publishes):

- A helper's parameters may not flow into a template string or into the props of a nested `<svg>` (`provenance`). They may feed numeric attributes of `rect`, `circle`, `line`, `path`. So glyph helpers take no arguments, and the call site places them with a `transform` built from widget-local consts: `<g transform={`translate(${c1 + 12} ${rowA + 16})`}>{glyphCloudRun()}</g>`.
- Words you type are literal `<text data-claude-text-id='…'>` written outside helpers; a helper draws shapes only. The marker's `!` is therefore a line and a dot, not a glyph.
- Colour is tokens only: `var(--cds-…)` strings, no hex, no named colour, no `light-dark()`. A `typed_colour` diagnostic in the publish ack or the screenshot read is a defect to clear before publishing, not noise.
- The page tokens inside the widget frame differ from the page's own (token sheet, light / dark): categorical `-1` #2A78D6 / #3987E5, `-2` #EB6834 / #D95926, `-3` #1BAF7A / #189E70, `-4` #0D366B / #9EC5F4 (blue, not yellow), `-5` #D55181 both, `-6` #008300, `-7` #4A3AA7 / #9085E9, `-8` #E66767 both; status good/warning/serious/critical #0CA30C / #FAB219 / #EC835A / #D03B3B both; text-secondary #52514E / #C3C2B7; chart-axis #C3C2B7 / #383835 (1.75:1 and 1.55:1 on the page, too faint for an edge). So edges use `--cds-text-secondary` (never the axis token) and environment bands use `-5` at three strengths. These in-frame values are what the prelude's tokens resolve to.

Every module starts with this prelude (the composed example shows it in place):

```jsx
const cat = { compute: 'var(--cds-chart-categorical-1)', data: 'var(--cds-chart-categorical-2)', networking: 'var(--cds-chart-categorical-7)', security: 'var(--cds-chart-categorical-6)', operations: 'var(--cds-chart-categorical-3)', neutral: 'var(--cds-text-secondary)' };
const mark = 'var(--cds-chart-status-critical)', sym = 'var(--cds-page-bg)', edge = 'var(--cds-text-secondary)';
const ink = 'var(--cds-text-primary)', quiet = 'var(--cds-text-secondary)', grid = 'var(--cds-chart-grid)', tint = 'var(--cds-chart-reference-tint)';
const env = 'var(--cds-chart-categorical-5)';
const W = 184, H = 56;
```

`sym` is `var(--cds-page-bg)`, so a glyph's symbol takes the theme's page colour on its hexagon, in both themes (checked on a scratch Doc, light and dark). Should the validator ever flag it, draw glyphs in the accent form instead: hexagon `fill={c} fillOpacity='0.12' stroke={c} strokeWidth='1.25'` and the symbol in `{c}`. `edge` is `--cds-text-secondary`: 7.73:1 light / 10.19:1 dark on the page (`gcp-visual-grammar.md` Edges). Every `<text>` sets `fill` (`ink` for names, `quiet` for edge labels, notes and boundary names). One `<marker>` per diagram in `<defs>`, referenced by every connector.

## Icon node

A box in the category colour with the product glyph at its left and two literal lines of text: the product name (13/600) and the instance name (11.5, quiet). Width 184 holds 17 characters of name (Artifact Registry, Cloud Monitoring, unabbreviated) and 20 of body; names are the grammar's product names, drawn as `WIF pool` / `WIF provider` and `Load Balancing` for the two long ones. Widen for a longer instance name rather than letting it run over the border; never abbreviate a product.

```jsx
const node = (x, y, colour) => <rect x={x} y={y} width={W} height={H} rx='8' fill='none' stroke={colour} strokeWidth='1.25'/>;
// usage, with c1 and rowA widget-local consts:
<g data-claude-anchor='node-ingest-api'>{node(c1, rowA, cat.compute)}<g transform={`translate(${c1 + 12} ${rowA + 16})`}>{glyphCloudRun()}</g><text data-claude-text-id='n1-name' x={c1 + 44} y={rowA + 24} fontWeight='600' fill={ink}>Cloud Run</text><text data-claude-text-id='n1-body' x={c1 + 44} y={rowA + 40} fontSize='11.5' fill={quiet}>ingest-api</text></g>
```

Glyph helpers, one per file in `assets/gcp-icons/` (the SVG body with JSX attribute names, the hexagon fill on its category token, the symbol on `sym`). Paste the ones the diagram uses:

```jsx
const glyphArtifactRegistry = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.operations}/><path d='M12 6.5l5 2.5v6l-5 2.5-5-2.5V9zM7 9l5 2.5L17 9M12 11.5v6' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphBigquery = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.data}/><circle cx='11' cy='11' r='3.8' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M14 14l3.5 3.5' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphCiJob = () => <g><g fill={cat.operations}><path fillRule='evenodd' d='M5 4h14a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 19 20H5a1.5 1.5 0 0 1-1.5-1.5v-13A1.5 1.5 0 0 1 5 4zm0 2v12h14V6zm4 2.5l6 3.5-6 3.5z'/></g></g>;
const glyphCloudBuild = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.operations}/><path d='M7 16.5l6-6' stroke={sym} strokeWidth='2.4' strokeLinecap='round'/><rect x='11' y='6.5' width='6' height='3.6' rx='1' transform='rotate(45 14 8.3)' fill={sym}/></g>;
const glyphCloudFunctions = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.compute}/><path d='M10 7.5c-1.5 0-2 .8-2 2v1c0 .8-.5 1.5-1.5 1.5 1 0 1.5.7 1.5 1.5v1c0 1.2.5 2 2 2M14 7.5c1.5 0 2 .8 2 2v1c0 .8.5 1.5 1.5 1.5-1 0-1.5.7-1.5 1.5v1c0 1.2-.5 2-2 2' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphCloudLoadBalancing = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.networking}/><circle cx='7' cy='12' r='1.5' fill={sym}/><circle cx='17' cy='7.5' r='1.4' fill={sym}/><circle cx='17' cy='12' r='1.4' fill={sym}/><circle cx='17' cy='16.5' r='1.4' fill={sym}/><path d='M7 12L17 7.5M7 12h10M7 12l10 4.5' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphCloudLogging = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.operations}/><path d='M7.5 8h9M7.5 12h9M7.5 16h5.5' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphCloudMonitoring = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.operations}/><path d='M6.5 16.5l3.5-4 2.5 2.5 5-6' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M6.5 7v9.5H17.5' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphCloudRun = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.compute}/><path d='M9.5 7.5l7 4.5-7 4.5z' fill={sym}/></g>;
const glyphCloudScheduler = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.operations}/><circle cx='12' cy='12' r='5' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M12 9v3.2l2 1.3' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphCloudSql = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.data}/><ellipse cx='12' cy='8' rx='4.5' ry='1.8' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M7.5 8v8c0 1 2 1.8 4.5 1.8s4.5-.8 4.5-1.8V8M7.5 12c0 1 2 1.8 4.5 1.8s4.5-.8 4.5-1.8' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphCloudStorage = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.data}/><path d='M7 8h10l-1.2 8.5h-7.6z' fill={sym}/><ellipse cx='12' cy='8' rx='5' ry='1.4' fill={sym} stroke='none'/></g>;
const glyphExternalSystem = () => <g><g fill={cat.neutral}><path fillRule='evenodd' d='M4 6a2 2 0 0 1 2-2h7v2H6v12h12v-7h2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM14 4h6v6h-2V7.4l-6.3 6.3-1.4-1.4L16.6 6H14z'/></g></g>;
const glyphFirestore = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.data}/><path d='M8 6.5h6l2.5 2.5v8.5H8z' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M10 12h4.5M10 14.5h4.5' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphGitlab = () => <g><g fill={cat.operations}><path d='M12 20.5l-7-5.3 1.9-6 1.9 4.2h6.4l1.9-4.2 1.9 6z M12 20.5l-2.6-4.3h5.2z M6.9 9.2L8.5 4l1.9 5.2z M17.1 9.2L15.5 4l-1.9 5.2z'/></g></g>;
const glyphIam = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.security}/><path d='M12 6l5 2v4c0 3-2.2 5-5 6-2.8-1-5-3-5-6V8z' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M9.8 12l1.6 1.6 3-3' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphPubsub = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.data}/><circle cx='12' cy='12' r='1.7' fill={sym}/><circle cx='7' cy='8' r='1.4' fill={sym}/><circle cx='17' cy='8' r='1.4' fill={sym}/><circle cx='12' cy='17' r='1.4' fill={sym}/><path d='M12 12L7 8M12 12l5-4M12 12v5' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphSecretManager = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.security}/><circle cx='9.5' cy='12' r='2.6' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M12 12h5.5M15.5 12v2.2' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
const glyphServiceAccount = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.security}/><circle cx='12' cy='9.5' r='2.3' fill={sym}/><path d='M7.5 16.5c0-2.6 2-4 4.5-4s4.5 1.4 4.5 4z' fill={sym}/><rect x='14' y='13.5' width='4' height='4' rx='.8' fill={sym}/></g>;
const glyphUser = () => <g><g fill={cat.neutral}><circle cx='12' cy='8' r='4'/><path d='M4 20c0-4.4 3.6-7 8-7s8 2.6 8 7z'/></g></g>;
const glyphVpc = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.networking}/><rect x='6.5' y='6.5' width='11' height='11' rx='1.5' strokeDasharray='2.4 1.8' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><circle cx='12' cy='12' r='1.8' fill={sym}/></g>;
const glyphWorkloadIdentityFederation = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.security}/><circle cx='7.5' cy='12' r='2.2' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><circle cx='16.5' cy='12' r='2.2' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M10 10.5h4M14 10.5l-1-1M10 13.5h4M10 13.5l1 1' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>;
```

## Labelled edge

One helper for the three line styles; the kind is the inventory edge kind. The label is a literal text beside the line (above a level run, right of an upright one), at most three words.

```jsx
const link = (d, kind) => <path d={d} fill='none' stroke={edge} strokeWidth='1.25' strokeDasharray={kind === 'async' ? '6 4' : kind === 'call' ? 'none' : '1.5 3'} markerEnd='url(#arch-arrow)'/>;
// in <defs>:
<marker id='arch-arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='6' markerHeight='6' orient='auto-start-reverse'><path d='M0 0L10 5L0 10z' fill={edge}/></marker>
// usage: solid call, dashed async, dotted iam or trust; the path starts and ends on a box edge
{link(`M${c1 + W} ${rowA + 28}H${c2}`, 'async')}
<text data-claude-text-id='edge-publish' x={(c1 + W + c2) / 2} y={rowA - 8} textAnchor='middle' fontSize='11.5' fill={quiet}>topic orders</text>
// an upright run: label to its right
{link(`M${c3 + W / 2} ${rowA + H}V${rowB}`, 'call')}
<text data-claude-text-id='edge-insert' x={c3 + W / 2 + 10} y={rowA + H + 24} fontSize='11.5' fill={quiet}>insert</text>
```

## Boundary box

Three helpers, one per outline style; the name is a literal quiet text top-left (`x + 16`, `y + 20`). Children sit 16 in from the sides and 16 above the foot; the name line takes 32. A VPC outline carries `glyphVpc()` before its name; a subnet is the same thin outline nested inside its VPC.

```jsx
const org = (x, y, w, h) => <rect x={x} y={y} width={w} height={h} rx='8' fill='none' stroke={edge} strokeWidth='1.25' strokeDasharray='6 4'/>;
const project = (x, y, w, h) => <rect x={x} y={y} width={w} height={h} rx='8' fill={tint}/>;
const vpc = (x, y, w, h) => <rect x={x} y={y} width={w} height={h} rx='8' fill='none' stroke={edge} strokeWidth='1'/>;
// usage
<g data-claude-anchor='org-example'>{org(24, 52, 712, 288)}<text data-claude-text-id='org-name' x='40' y='72' fontSize='11.5' fill={quiet}>folder: example-folder</text></g>
<g data-claude-anchor='vpc-main'>{vpc(vx, vy, 298, 184)}<g transform={`translate(${vx + 8} ${vy + 6})`}>{glyphVpc()}</g><text data-claude-text-id='vpc-name' x={vx + 38} y={vy + 22} fontSize='11.5' fill={quiet}>vpc-main</text></g>
```

## Environment band

A pill behind the project label in one hue at three strengths, the env word in capitals on it, then the project id. Strengths: DEV `0.1, 0.45`, STAGE `0.2, 0.7`, PROD `0.32, 1` (fill opacity, stroke opacity). Width: 44 for DEV, 56 for STAGE, 52 for PROD.

```jsx
const band = (x, y, w, fo, so) => <rect x={x} y={y} width={w} height='20' rx='4' fill={env} fillOpacity={fo} stroke={env} strokeOpacity={so} strokeWidth='1'/>;
// usage, on a project box at (24, 52)
{band(32, 58, 52, 0.32, 1)}<text data-claude-text-id='env-prod' x='58' y='72' textAnchor='middle' fontSize='11.5' fontWeight='600' fill={ink}>PROD</text><text data-claude-text-id='project-id' x='94' y='72' fontWeight='600' fill={ink}>tenant-prod</text>
```

## Swimlane

A full-width lane for a data-flow diagram, one per project or env the flow crosses; the lane name is a literal quiet text top-left and the flow's nodes sit inside it.

```jsx
const lane = (x, y, w, h) => <rect x={x} y={y} width={w} height={h} rx='8' fill='none' stroke={grid} strokeWidth='1'/>;
// usage
<g data-claude-anchor='lane-stage'>{lane(24, ly, 712, 96)}<text data-claude-text-id='lane-name' x='40' y={ly + 20} fontSize='11.5' fill={quiet}>lane: tenant-stage</text></g>
```

## Trust-crossing marker

A disc of radius 7 in the marker colour with a `!` drawn as shapes, placed on the edge where it crosses the trust boundary (on a level edge the boundary's x; on an upright one the boundary's y). The same helper draws the key entry.

```jsx
const crossing = (x, y) => <g><circle cx={x} cy={y} r='7' fill={mark}/><line x1={x} y1={y - 4} x2={x} y2={y + 0.5} stroke={sym} strokeWidth='1.8' strokeLinecap='round'/><circle cx={x} cy={y + 3.4} r='1' fill={sym}/></g>;
// usage: the trust edge rises from outside into the WIF node through the project's foot (y = 268)
{link(`M${c1 + W / 2} 304V${rowB + H}`, 'trust')}
<text data-claude-text-id='edge-trust' x={c1 + W / 2 + 10} y='292' fontSize='11.5' fill={quiet}>gitlab oidc</text>
<g data-claude-anchor='trust-crossing'>{crossing(c1 + W / 2, 268)}</g>
{crossing(400, 333)}<text data-claude-text-id='key-marker' x='414' y='337' fontSize='11.5' fill={quiet}>crosses a trust boundary</text>
```

## Composed example

Five nodes in a `PROD` project: Cloud Run → Pub/Sub (dashed) → Cloud Run → BigQuery (down), a WIF pool reached by a dotted trust edge rising from outside with the marker on the project's foot, and a key strip. Published as written: it was published unchanged on a scratch Doc (ack `diagnostics: []`, no `typed_colour`, light and dark read); the line below hashes sha256 `df09ac3f763bfb788c393ecd2a91fa2407f3f1b37e9b92d750295e1eb2e1137e` (6960 chars).

```jsx
export default () => { const cat = { compute: 'var(--cds-chart-categorical-1)', data: 'var(--cds-chart-categorical-2)', networking: 'var(--cds-chart-categorical-7)', security: 'var(--cds-chart-categorical-6)', operations: 'var(--cds-chart-categorical-3)', neutral: 'var(--cds-text-secondary)' }; const mark = 'var(--cds-chart-status-critical)', sym = 'var(--cds-page-bg)', edge = 'var(--cds-text-secondary)'; const ink = 'var(--cds-text-primary)', quiet = 'var(--cds-text-secondary)', grid = 'var(--cds-chart-grid)', tint = 'var(--cds-chart-reference-tint)'; const env = 'var(--cds-chart-categorical-5)'; const W = 184, H = 56; const rowA = 100, rowB = 196, c1 = 40, c2 = 264, c3 = 488; const glyphCloudRun = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.compute}/><path d='M9.5 7.5l7 4.5-7 4.5z' fill={sym}/></g>; const glyphPubsub = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.data}/><circle cx='12' cy='12' r='1.7' fill={sym}/><circle cx='7' cy='8' r='1.4' fill={sym}/><circle cx='17' cy='8' r='1.4' fill={sym}/><circle cx='12' cy='17' r='1.4' fill={sym}/><path d='M12 12L7 8M12 12l5-4M12 12v5' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>; const glyphBigquery = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.data}/><circle cx='11' cy='11' r='3.8' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M14 14l3.5 3.5' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>; const glyphWorkloadIdentityFederation = () => <g><path d='M12 1.5l9 5.2v10.6l-9 5.2-9-5.2V6.7z' fill={cat.security}/><circle cx='7.5' cy='12' r='2.2' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><circle cx='16.5' cy='12' r='2.2' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/><path d='M10 10.5h4M14 10.5l-1-1M10 13.5h4M10 13.5l1 1' stroke={sym} strokeWidth='1.6' strokeLinecap='round' strokeLinejoin='round' fill='none'/></g>; const node = (x, y, colour) => <rect x={x} y={y} width={W} height={H} rx='8' fill='none' stroke={colour} strokeWidth='1.25'/>; const link = (d, kind) => <path d={d} fill='none' stroke={edge} strokeWidth='1.25' strokeDasharray={kind === 'async' ? '6 4' : kind === 'call' ? 'none' : '1.5 3'} markerEnd='url(#arch-arrow)'/>; const crossing = (x, y) => <g><circle cx={x} cy={y} r='7' fill={mark}/><line x1={x} y1={y - 4} x2={x} y2={y + 0.5} stroke={sym} strokeWidth='1.8' strokeLinecap='round'/><circle cx={x} cy={y + 3.4} r='1' fill={sym}/></g>; const band = (x, y, w, fo, so) => <rect x={x} y={y} width={w} height='20' rx='4' fill={env} fillOpacity={fo} stroke={env} strokeOpacity={so} strokeWidth='1'/>; const swatch = (x, y, colour) => <rect x={x} y={y} width='10' height='10' rx='2' fill={colour}/>; return <svg viewBox='0 0 760 356' role='img' aria-label='Orders reach BigQuery via one topic; only the GitLab identity crosses into prod' fontSize='13'> <defs><marker id='arch-arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='6' markerHeight='6' orient='auto-start-reverse'><path d='M0 0L10 5L0 10z' fill={edge}/></marker></defs> <text data-claude-text-id='title' x='24' y='28' fontSize='15' fontWeight='600' fill={ink}>Orders reach BigQuery via one topic; only the GitLab identity crosses into prod</text> <g data-claude-anchor='project-tenant-prod'><rect x='24' y='52' width='712' height='216' rx='8' fill={tint}/>{band(32, 58, 52, 0.32, 1)}<text data-claude-text-id='env-prod' x='58' y='72' textAnchor='middle' fontSize='11.5' fontWeight='600' fill={ink}>PROD</text><text data-claude-text-id='project-id' x='94' y='72' fontWeight='600' fill={ink}>tenant-prod</text></g> <g data-claude-anchor='connectors'>{link(`M${c1 + W} ${rowA + 28}H${c2}`, 'async')}{link(`M${c2 + W} ${rowA + 28}H${c3}`, 'call')}{link(`M${c3 + W / 2} ${rowA + H}V${rowB}`, 'call')}{link(`M${c1 + W / 2} 304V${rowB + H}`, 'trust')}</g> <text data-claude-text-id='edge-publish' x={(c1 + W + c2) / 2} y='92' textAnchor='middle' fontSize='11.5' fill={quiet}>topic orders</text> <text data-claude-text-id='edge-push' x={(c2 + W + c3) / 2} y='92' textAnchor='middle' fontSize='11.5' fill={quiet}>push HTTPS</text> <text data-claude-text-id='edge-insert' x={c3 + W / 2 + 10} y={rowA + H + 24} fontSize='11.5' fill={quiet}>insert</text> <text data-claude-text-id='edge-trust' x={c1 + W / 2 + 10} y='292' fontSize='11.5' fill={quiet}>gitlab oidc</text> <g data-claude-anchor='node-ingest-api'>{node(c1, rowA, cat.compute)}<g transform={`translate(${c1 + 12} ${rowA + 16})`}>{glyphCloudRun()}</g><text data-claude-text-id='n1-name' x={c1 + 44} y={rowA + 24} fontWeight='600' fill={ink}>Cloud Run</text><text data-claude-text-id='n1-body' x={c1 + 44} y={rowA + 40} fontSize='11.5' fill={quiet}>ingest-api</text></g> <g data-claude-anchor='node-orders-topic'>{node(c2, rowA, cat.data)}<g transform={`translate(${c2 + 12} ${rowA + 16})`}>{glyphPubsub()}</g><text data-claude-text-id='n2-name' x={c2 + 44} y={rowA + 24} fontWeight='600' fill={ink}>Pub/Sub</text><text data-claude-text-id='n2-body' x={c2 + 44} y={rowA + 40} fontSize='11.5' fill={quiet}>orders</text></g> <g data-claude-anchor='node-worker'>{node(c3, rowA, cat.compute)}<g transform={`translate(${c3 + 12} ${rowA + 16})`}>{glyphCloudRun()}</g><text data-claude-text-id='n3-name' x={c3 + 44} y={rowA + 24} fontWeight='600' fill={ink}>Cloud Run</text><text data-claude-text-id='n3-body' x={c3 + 44} y={rowA + 40} fontSize='11.5' fill={quiet}>worker</text></g> <g data-claude-anchor='node-orders-dw'>{node(c3, rowB, cat.data)}<g transform={`translate(${c3 + 12} ${rowB + 16})`}>{glyphBigquery()}</g><text data-claude-text-id='n4-name' x={c3 + 44} y={rowB + 24} fontWeight='600' fill={ink}>BigQuery</text><text data-claude-text-id='n4-body' x={c3 + 44} y={rowB + 40} fontSize='11.5' fill={quiet}>orders_dw</text></g> <g data-claude-anchor='node-wif-pool'>{node(c1, rowB, cat.security)}<g transform={`translate(${c1 + 12} ${rowB + 16})`}>{glyphWorkloadIdentityFederation()}</g><text data-claude-text-id='n5-name' x={c1 + 44} y={rowB + 24} fontWeight='600' fill={ink}>WIF pool</text><text data-claude-text-id='n5-body' x={c1 + 44} y={rowB + 40} fontSize='11.5' fill={quiet}>gitlab-pool</text></g> <g data-claude-anchor='trust-crossing'>{crossing(c1 + W / 2, 268)}</g> <g data-claude-anchor='key'>{swatch(24, 328, cat.compute)}<text data-claude-text-id='key-compute' x='40' y='337' fontSize='11.5' fill={quiet}>compute</text>{swatch(110, 328, cat.data)}<text data-claude-text-id='key-data' x='126' y='337' fontSize='11.5' fill={quiet}>data/analytics</text>{swatch(240, 328, cat.security)}<text data-claude-text-id='key-security' x='256' y='337' fontSize='11.5' fill={quiet}>security/identity</text>{crossing(400, 333)}<text data-claude-text-id='key-marker' x='414' y='337' fontSize='11.5' fill={quiet}>crosses a trust boundary</text></g> </svg>; };
```

Place it with the prose in one batch, then look:

```
batch(container = C, batch = [
 {"$lid":"w","verb":"create","object":"node","engine":"widget","payload":{"parent":{"object":"file","id":"<tab file id>"},"code":"<the line above>"}},
 {"verb":"update","ref":{"object":"node","id":"<body id>"},"engine":"prose","payload":{"ops":[{"op":"replace","target":{"kind":"blocks","ids":["<pending block id>"]},"with":{"as":"markdown","blocks":{"dia":{"type":"embed","ref":"node/$lid:w","caption":"composed example · 5 nodes, 4 edges, 1 trust crossing"}},"from":{"kind":"inline","content":"## <section>\n\n<?claude block dia?>\n\n<one sentence of reading>"}}}]}}
])
read(ref = {"object":"node","id":"<widget id>"}, engine = "widget", container = C, payload = {"kind":"screenshot"})
```

The screenshot is the light theme. For dark, open the Doc in Chrome with the page in dark mode (or toggle `data-mode='dark'` on `<html>`) and screenshot; the Docs tools have no dark read.
