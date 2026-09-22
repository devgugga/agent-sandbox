// Type aliases over the generated `schema.d.ts` (spec §9.1, §9.4). No
// hand-written shapes here — every field name and type comes straight from
// the daemon's OpenAPI contract, so a contract change fails `tsc`, not the
// user. Kept in `types/` rather than re-exported piecemeal from `api/client.ts`
// so components can import node shapes without pulling in the client's fetch
// wrappers.
import type { components } from "../api/schema";

export type ProjectNode = components["schemas"]["ProjectNode"];
export type CheckoutNode = components["schemas"]["CheckoutNode"];
export type SessionNode = components["schemas"]["SessionNode"];
export type UnregisteredNode = components["schemas"]["UnregisteredNode"];
export type WorkspaceStatus = components["schemas"]["WorkspaceStatus"];
export type CheckoutKind = components["schemas"]["CheckoutKind"];
export type SessionState = components["schemas"]["SessionState"];
export type AgentKind = components["schemas"]["AgentKind"];
