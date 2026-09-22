// DetailPanel — everything a tree row cannot hold for the selected node
// (spec §9.2, §9.4): full path, workspace id, status and reason, branch
// and where it was read (sandbox or host), sessions with state and
// timestamps. This area becomes the terminal workbench in item 2 — it
// stays a plain, read-only summary here.
import { UNREGISTERED_LABEL, branchLabel, statusLabel } from "../lib/labels";
import type { Row } from "../lib/tree";
import type { CheckoutNode, ProjectNode, SessionNode, UnregisteredNode } from "../types/tree";

export interface DetailPanelProps {
  selection: Row | null;
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs uppercase tracking-wide text-fg-muted">{label}</dt>
      <dd className="text-sm text-fg">{value}</dd>
    </div>
  );
}

function formatTimestamp(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function ProjectDetails({ project }: { project: ProjectNode }) {
  return (
    <dl className="flex flex-col gap-3">
      <Field label="Project" value={project.name} />
      <Field label="Primary path" value={project.primary_path} />
      <Field label="Integration branch" value={project.integration_branch} />
      <Field label="Status" value={project.error ? `error: ${project.error}` : "ok"} />
    </dl>
  );
}

function CheckoutDetails({ project, checkout }: { project: ProjectNode; checkout: CheckoutNode }) {
  return (
    <dl className="flex flex-col gap-3">
      <Field label="Project" value={project.name} />
      <Field label="Full path" value={checkout.path} />
      <Field label="Workspace" value={checkout.workspace} />
      <Field label="Kind" value={checkout.kind} />
      <Field label="Status" value={statusLabel(checkout.status, checkout.reason)} />
      <Field
        label="Branch"
        value={branchLabel(checkout.branch, checkout.detached, checkout.host_branch)}
      />
      <Field label="Read from" value={checkout.host_branch ? "host" : "sandbox"} />
      {checkout.error && <Field label="Error" value={checkout.error} />}
      <div className="flex flex-col gap-1">
        <dt className="text-xs uppercase tracking-wide text-fg-muted">Sessions</dt>
        {checkout.sessions.length === 0 ? (
          <dd className="text-sm text-fg-muted">none</dd>
        ) : (
          checkout.sessions.map((session) => (
            <dd key={session.id} className="text-sm text-fg">
              {session.agent} · {session.state} · {session.title}
            </dd>
          ))
        )}
      </div>
    </dl>
  );
}

function SessionDetails({
  project,
  checkout,
  session,
}: {
  project: ProjectNode;
  checkout: CheckoutNode;
  session: SessionNode;
}) {
  return (
    <dl className="flex flex-col gap-3">
      <Field label="Project" value={project.name} />
      <Field label="Checkout" value={checkout.workspace} />
      <Field label="Agent" value={session.agent} />
      <Field label="State" value={session.state} />
      <Field label="Title" value={session.title} />
      <Field label="Working directory" value={session.cwd} />
      <Field label="Started at" value={formatTimestamp(session.started_at)} />
      <Field label="Ended at" value={formatTimestamp(session.ended_at)} />
      <Field label="Last healthy at" value={formatTimestamp(session.last_healthy_at)} />
    </dl>
  );
}

function UnregisteredDetails({
  project,
  unregistered,
}: {
  project: ProjectNode;
  unregistered: UnregisteredNode;
}) {
  return (
    <dl className="flex flex-col gap-3">
      <Field label="Project" value={project.name} />
      <Field label="Path" value={unregistered.path} />
      <Field
        label="Branch"
        value={branchLabel(unregistered.branch, unregistered.detached, false)}
      />
      <Field label="Status" value={UNREGISTERED_LABEL} />
      <Field label="Missing" value={unregistered.missing ? "yes" : "no"} />
      <Field label="Prunable" value={unregistered.prunable ? "yes" : "no"} />
    </dl>
  );
}

export function DetailPanel({ selection }: DetailPanelProps) {
  if (!selection) {
    return (
      <aside aria-label="Details" className="p-4 text-sm text-fg-muted">
        Select a project, checkout or session to see its details.
      </aside>
    );
  }

  return (
    <aside aria-label="Details" className="overflow-y-auto p-4">
      {selection.kind === "project" && <ProjectDetails project={selection.project} />}
      {selection.kind === "checkout" && (
        <CheckoutDetails project={selection.project} checkout={selection.checkout} />
      )}
      {selection.kind === "session" && (
        <SessionDetails
          project={selection.project}
          checkout={selection.checkout}
          session={selection.session}
        />
      )}
      {selection.kind === "unregistered" && (
        <UnregisteredDetails project={selection.project} unregistered={selection.unregistered} />
      )}
    </aside>
  );
}
