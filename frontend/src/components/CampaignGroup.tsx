import type { Campaign, Document } from "../lib/api";
import { plural } from "../lib/api";
import { Icon } from "./Icon";
import { DocumentCard } from "./DocumentCard";
import { DocumentCoverCard } from "./DocumentCoverCard";

export function CampaignGroup({
  campaign,
  documents,
  campaigns,
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
  onDeleteDoc,
  onRetitleDoc,
  onAssignCampaign,
  onScenarioOrder,
}: {
  campaign: Campaign | null;
  documents: Document[];
  campaigns: Campaign[];
  view: "grid" | "list";
  embeddingConfigured: boolean;
  canWrite?: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onUpload: (campaignId: string | null) => void;
  onEdit?: (campaign: Campaign) => void;
  onDelete?: (campaign: Campaign) => void;
  onOpenDoc: (doc: Document) => void;
  onReindexDoc: (doc: Document) => void;
  onDeleteDoc: (doc: Document) => void;
  onRetitleDoc: (doc: Document, title: string) => void;
  onAssignCampaign: (doc: Document, campaignId: string | null) => void;
  onScenarioOrder: (doc: Document, order: number) => void;
}) {
  const ordered = [...documents].sort(
    (a, b) => a.sort_order - b.sort_order || a.title.localeCompare(b.title),
  );
  const content = (
    <>
      {documents.length ? (
        <div className={view === "grid" ? "document-grid" : "document-list"}>
          {ordered.map((doc) =>
            view === "grid" ? (
              <DocumentCoverCard
                key={doc.id}
                document={doc}
                campaigns={campaigns}
                canWrite={canWrite}
                onCampaignChange={(campaignId) => onAssignCampaign(doc, campaignId)}
                onOrderChange={(order) => onScenarioOrder(doc, order)}
                onOpen={() => onOpenDoc(doc)}
                onReindex={() => onReindexDoc(doc)}
                onDelete={() => onDeleteDoc(doc)}
                onRetitle={(title) => onRetitleDoc(doc, title)}
              />
            ) : (
              <DocumentCard
                key={doc.id}
                document={doc}
                embeddingConfigured={embeddingConfigured}
                canWrite={canWrite}
                campaigns={campaigns}
                onCampaignChange={(campaignId) => onAssignCampaign(doc, campaignId)}
                onOrderChange={(order) => onScenarioOrder(doc, order)}
                onOpen={() => onOpenDoc(doc)}
                onReindex={() => onReindexDoc(doc)}
                onDelete={() => onDeleteDoc(doc)}
                onRetitle={(title) => onRetitleDoc(doc, title)}
              />
            ),
          )}
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
            <span className="role-count">{plural(documents.length, "book")}</span>
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
          <span className="role-count">{plural(documents.length, "book")}</span>
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
