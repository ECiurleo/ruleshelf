import type { Campaign, Document } from "../lib/api";
import { plural } from "../lib/api";
import { Icon } from "./Icon";
import { ScenarioGroup } from "./ScenarioGroup";

export function CampaignGroup({
  campaign,
  documents,
  view,
  embeddingConfigured,
  canWrite = true,
  collapsed,
  onToggleCollapsed,
  onUpload,
  onEdit,
  onDelete,
  onOpenDoc,
  onReindexDoc,
  onOcrDoc,
  onDeleteDoc,
  onEditDoc,
}: {
  campaign: Campaign | null;
  documents: Document[];
  view: "grid" | "list";
  embeddingConfigured: boolean;
  canWrite?: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onUpload: (campaignId: string | null, scenarioId?: string | null) => void;
  onEdit?: (campaign: Campaign) => void;
  onDelete?: (campaign: Campaign) => void;
  onOpenDoc: (doc: Document) => void;
  onReindexDoc: (doc: Document) => void;
  onOcrDoc: (doc: Document) => void;
  onDeleteDoc: (doc: Document) => void;
  onEditDoc: (doc: Document) => void;
}) {
  const ordered = [...documents].sort(
    (a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title),
  );
  const byId = new Map(documents.map((doc) => [doc.id, doc]));
  const filesByLead = new Map<string, Document[]>();
  for (const doc of ordered) {
    if (doc.scenario_id && byId.has(doc.scenario_id)) {
      const files = filesByLead.get(doc.scenario_id) ?? [];
      files.push(doc);
      filesByLead.set(doc.scenario_id, files);
    }
  }
  const scenarios = ordered
    .filter((doc) => !(doc.scenario_id && byId.has(doc.scenario_id)))
    .map((lead) => ({ lead, files: filesByLead.get(lead.id) ?? [] }));
  const fileCount = scenarios.reduce((total, entry) => total + entry.files.length, 0);
  const scenarioCount = plural(scenarios.length, "scenario") +
    (fileCount ? ` · ${plural(fileCount, "file")}` : "");

  const content = (
    <>
      {scenarios.length ? (
        <div className={view === "grid" ? "document-grid" : "document-list"}>
          {scenarios.map(({ lead, files }) => (
            <ScenarioGroup
              key={lead.id}
              lead={lead}
              files={files}
              view={view}
              embeddingConfigured={embeddingConfigured}
              canWrite={canWrite}
              onOpenDoc={onOpenDoc}
              onReindexDoc={onReindexDoc}
              onOcrDoc={onOcrDoc}
              onDeleteDoc={onDeleteDoc}
              onEditDoc={onEditDoc}
              onAddFile={() => onUpload(campaign?.id ?? null, lead.id)}
            />
          ))}
        </div>
      ) : campaign && canWrite ? (
        <button className="dropzone small" onClick={() => onUpload(campaign.id)}>
          <Icon name="plus" size={18} />
          Add a scenario to {campaign.title}
        </button>
      ) : null}
    </>
  );

  if (!campaign) {
    return (
      <section className="campaign-group ungrouped">
        <div className="campaign-head">
          <div>
            <h3>Ungrouped campaign documents</h3>
            <p className="campaign-sub">Choose a campaign on each book to file it.</p>
          </div>
          <div className="campaign-head-actions">
            <span className="role-count">{scenarioCount}</span>
            <button
              className="button ghost small collapse-toggle"
              onClick={onToggleCollapsed}
              aria-expanded={!collapsed}
            >
              <Icon name="chevron" size={14} className={collapsed ? "" : "open"} />
              {collapsed ? "Show" : "Hide"} scenarios
            </button>
          </div>
        </div>
        {collapsed ? null : content}
      </section>
    );
  }

  return (
    <section className="campaign-group">
      <div className="campaign-head">
        <div>
          <h3>{campaign.title}</h3>
          {campaign.description && <p className="campaign-sub">{campaign.description}</p>}
        </div>
        <div className="campaign-head-actions">
          <span className="role-count">{scenarioCount}</span>
          <button
            className="button ghost small collapse-toggle"
            onClick={onToggleCollapsed}
            aria-expanded={!collapsed}
          >
            <Icon name="chevron" size={14} className={collapsed ? "" : "open"} />
            {collapsed ? "Show" : "Hide"} scenarios
          </button>
          {canWrite && (
            <button className="button ghost small" onClick={() => onUpload(campaign.id)}>
              <Icon name="plus" size={15} /> Add scenario
            </button>
          )}
          {canWrite && onEdit && onDelete && (
            <>
              <button
                className="icon-button small"
                onClick={() => onEdit(campaign)}
                title="Edit campaign"
                aria-label="Edit campaign"
              >
                <Icon name="edit" size={15} />
              </button>
              <button
                className="icon-button small danger"
                onClick={() => onDelete(campaign)}
                title="Delete campaign (documents are kept)"
                aria-label="Delete campaign"
              >
                <Icon name="trash" size={15} />
              </button>
            </>
          )}
        </div>
      </div>
      {collapsed ? null : content}
    </section>
  );
}
