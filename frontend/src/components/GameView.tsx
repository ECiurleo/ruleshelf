import { useState } from "react";
import {
  plural,
  type Campaign,
  type Document,
  type Game,
  type GameType,
} from "../lib/api";
import { Icon } from "./Icon";
import { DocumentCard } from "./DocumentCard";
import { DocumentCoverCard } from "./DocumentCoverCard";
import { CampaignGroup } from "./CampaignGroup";

export function GameView({
  game,
  gameType,
  documents,
  campaigns,
  embeddingConfigured,
  canWrite = true,
  onUpload,
  onEdit,
  onDelete,
  onCampaignCreate,
  onCampaignEdit,
  onCampaignDelete,
  onAssignCampaign,
  onScenarioOrder,
  onOpenDoc,
  onReindexDoc,
  onDeleteDoc,
  onRetitleDoc,
}: {
  game: Game;
  gameType: GameType | undefined;
  documents: Document[];
  campaigns: Campaign[];
  embeddingConfigured: boolean;
  canWrite?: boolean;
  onUpload: (role: string, campaignId?: string | null) => void;
  onEdit: () => void;
  onDelete: () => void;
  onCampaignCreate: () => void;
  onCampaignEdit: (campaign: Campaign) => void;
  onCampaignDelete: (campaign: Campaign) => void;
  onAssignCampaign: (doc: Document, campaignId: string | null) => void;
  onScenarioOrder: (doc: Document, order: number) => void;
  onOpenDoc: (doc: Document) => void;
  onReindexDoc: (doc: Document) => void;
  onDeleteDoc: (doc: Document) => void;
  onRetitleDoc: (doc: Document, title: string) => void;
}) {
  const [view, setView] = useState<"grid" | "list">(() => {
    const saved = localStorage.getItem("ruleshelf:docView");
    return saved === "grid" ? "grid" : "list";
  });
  const chooseView = (next: "grid" | "list") => {
    setView(next);
    localStorage.setItem("ruleshelf:docView", next);
  };

  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try {
      return new Set<string>(JSON.parse(localStorage.getItem("ruleshelf:collapsedCampaigns") ?? "[]"));
    } catch {
      return new Set<string>();
    }
  });
  const toggleCollapsed = (key: string) => {
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      localStorage.setItem("ruleshelf:collapsedCampaigns", JSON.stringify([...next]));
      return next;
    });
  };

  const roles = gameType?.roles ?? [{ id: "core", label: "Core rules" }];
  const known = new Set(roles.map((role) => role.id));
  const extraRoles = [...new Set(documents.map((doc) => doc.role))].filter(
    (role) => !known.has(role),
  );
  const sections = [
    ...roles,
    ...extraRoles.map((role) => ({ id: role, label: role.replace(/_/g, " ") })),
  ];
  const processing = documents.filter(
    (doc) => doc.status === "pending" || doc.status === "processing",
  ).length;
  const errataCount = documents.filter((doc) => doc.role === "errata").length;

  const campaignDocs = documents.filter((doc) => doc.role === "campaign");
  const campaignIds = new Set(campaigns.map((campaign) => campaign.id));
  const ungrouped = campaignDocs.filter(
    (doc) => !doc.campaign_id || !campaignIds.has(doc.campaign_id),
  );
  const groups: { campaign: Campaign | null; documents: Document[] }[] = campaigns.map(
    (campaign) => ({
      campaign,
      documents: campaignDocs.filter((doc) => doc.campaign_id === campaign.id),
    }),
  );
  if (ungrouped.length) {
    groups.push({ campaign: null, documents: ungrouped });
  }

  const docProps = (doc: Document) => ({
    document: doc,
    canWrite,
    onOpen: () => onOpenDoc(doc),
    onReindex: () => onReindexDoc(doc),
    onDelete: () => onDeleteDoc(doc),
    onRetitle: (title: string) => onRetitleDoc(doc, title),
  });

  return (
    <div className="view game-view">
      <header className="game-header">
        <div className="game-heading">
          <span className={`type-badge type-${game.game_type}`}>{game.type_label}</span>
          <h1>{game.title}</h1>
          {game.description && <p className="game-description">{game.description}</p>}
          <div className="game-meta">
            <span>{plural(documents.length, "document")}</span>
            <span className="dot-sep" />
            <span>{game.chunk_count.toLocaleString()} indexed chunks</span>
            {errataCount > 0 && (
              <>
                <span className="dot-sep" />
                <span className="errata-note">
                  Errata applied · takes precedence over core rules
                </span>
              </>
            )}
            {processing > 0 && (
              <>
                <span className="dot-sep" />
                <span className="text-warn">
                  <span className="spinner" /> {processing} indexing
                </span>
              </>
            )}
          </div>
        </div>
        <div className="game-actions">
          <div className="view-switch" role="group" aria-label="Document layout">
            <button
              className={view === "grid" ? "selected" : ""}
              onClick={() => chooseView("grid")}
              title="Cover view"
              aria-label="Cover view"
            >
              <Icon name="grid" size={16} />
            </button>
            <button
              className={view === "list" ? "selected" : ""}
              onClick={() => chooseView("list")}
              title="List view"
              aria-label="List view"
            >
              <Icon name="list" size={16} />
            </button>
          </div>
          {canWrite && (
            <>
              <button className="button primary" onClick={() => onUpload("core")}>
                <Icon name="upload" size={17} /> Add document
              </button>
              <button
                className="icon-button"
                onClick={onEdit}
                title="Edit game"
                aria-label="Edit game"
              >
                <Icon name="edit" size={17} />
              </button>
              <button
                className="icon-button danger"
                onClick={onDelete}
                title="Delete game"
                aria-label="Delete game"
              >
                <Icon name="trash" size={17} />
              </button>
            </>
          )}
        </div>
      </header>

      {documents.length === 0 && campaigns.length === 0 ? (
        <div className="empty-panel">
          <span className="empty-mark">
            <Icon name="book" size={28} />
          </span>
          <h2>No rulebooks yet</h2>
          <p>
            {canWrite
              ? `Add the core ${game.game_type === "rpg" ? "rulebook" : "rules"} first — that becomes the primary source. Supplements and campaigns go alongside it.`
              : "This shelf is still empty. Ask an administrator to upload the books."}
          </p>
          {canWrite && (
            <>
              <button className="button primary" onClick={() => onUpload("core")}>
                <Icon name="upload" size={17} /> Upload the core rules
              </button>
              <p className="fine-print">PDF, EPUB, DOCX, Markdown or plain text.</p>
            </>
          )}
        </div>
      ) : (
        <div className="role-sections">
          {sections.map((role) => {
            if (role.id === "campaign") {
              const campaignCount = campaigns.length;
              return (
                <section className="role-section campaign-section" key={role.id}>
                  <div className="role-heading">
                    <h2>{role.label}</h2>
                    <div className="role-heading-right">
                      <span className="role-count">
                        {plural(campaignCount, "campaign")} ·{" "}
                        {plural(campaignDocs.length, "book")}
                      </span>
                      {canWrite && (
                        <button className="button ghost small" onClick={onCampaignCreate}>
                          <Icon name="plus" size={15} /> New campaign
                        </button>
                      )}
                    </div>
                  </div>

                  {groups.length ? (
                    <div className="campaign-groups">
                      {groups.map((group) => (
                        <CampaignGroup
                          key={group.campaign?.id ?? "ungrouped"}
                          campaign={group.campaign}
                          documents={group.documents}
                          campaigns={campaigns}
                          view={view}
                          embeddingConfigured={embeddingConfigured}
                          canWrite={canWrite}
                          collapsed={collapsed.has(group.campaign?.id ?? "ungrouped")}
                          onToggleCollapsed={() =>
                            toggleCollapsed(group.campaign?.id ?? "ungrouped")
                          }
                          onUpload={(campaignId) => onUpload("campaign", campaignId)}
                          onEdit={group.campaign ? onCampaignEdit : undefined}
                          onDelete={group.campaign ? onCampaignDelete : undefined}
                          onOpenDoc={onOpenDoc}
                          onReindexDoc={onReindexDoc}
                          onDeleteDoc={onDeleteDoc}
                          onRetitleDoc={onRetitleDoc}
                          onAssignCampaign={onAssignCampaign}
                          onScenarioOrder={onScenarioOrder}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="empty-panel compact campaign-empty">
                      <span className="empty-mark">
                        <Icon name="book" size={24} />
                      </span>
                      <h2>Group campaigns into scenarios</h2>
                      <p>
                        Create a campaign such as <em>The Enemy Within</em>, then add each
                        scenario as its own document. Existing campaign books can be assigned
                        from each book's campaign menu.
                      </p>
                      {canWrite && (
                        <button className="button primary" onClick={onCampaignCreate}>
                          <Icon name="plus" size={16} /> New campaign
                        </button>
                      )}
                    </div>
                  )}
                </section>
              );
            }

            const docs = documents.filter((doc) => doc.role === role.id);
            if (!docs.length && role.id !== "core") return null;
            return (
              <section className="role-section" key={role.id}>
                <div className="role-heading">
                  <h2>
                    {role.label}
                    {role.id === "core" && <span className="primary-tag">primary source</span>}
                  </h2>
                  <div className="role-heading-right">
                    <span className="role-count">{plural(docs.length, "book")}</span>
                    {canWrite && (
                      <button className="button ghost small" onClick={() => onUpload(role.id)}>
                        <Icon name="plus" size={15} /> Add
                      </button>
                    )}
                  </div>
                </div>
                {docs.length ? (
                  <div className={view === "grid" ? "document-grid" : "document-list"}>
                    {docs.map((doc) =>
                      view === "grid" ? (
                        <DocumentCoverCard key={doc.id} {...docProps(doc)} />
                      ) : (
                        <DocumentCard
                          key={doc.id}
                          {...docProps(doc)}
                          embeddingConfigured={embeddingConfigured}
                        />
                      ),
                    )}
                  </div>
                ) : canWrite ? (
                  <button className="dropzone small" onClick={() => onUpload(role.id)}>
                    <Icon name="plus" size={18} />
                    Add a {role.label.toLowerCase()} document
                  </button>
                ) : null}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
