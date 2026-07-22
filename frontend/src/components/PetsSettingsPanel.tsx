import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Upload, Trash2, Check, Cat, Sparkles, Loader2, ImageIcon, Pencil, X } from "lucide-react";
import { Button, Input } from "./ui";
import { toast } from "./ui/Toast";
import { cn } from "../lib/cn";
import {
  createPet,
  deletePet,
  expandPetActions,
  generatePet,
  getActiveGenerations,
  getActivePet,
  getGenerationStatus,
  getPet,
  listPets,
  renamePet,
  setActivePet,
  subscribeGenerationProgress,
  uploadSpritesheet,
  type ActiveJob,
  type GenerationProgress,
  type PetListItem,
} from "../api/pets";

const ACTION_PACKS = [
  { id: "basic", labelKey: "pets.actionPackBasic", descriptionKey: "pets.actionPackBasicDesc" },
  { id: "office", labelKey: "pets.actionPackOffice", descriptionKey: "pets.actionPackOfficeDesc" },
  { id: "interactive", labelKey: "pets.actionPackInteractive", descriptionKey: "pets.actionPackInteractiveDesc" },
];

const PET_STYLES = [
  { id: "pixel", labelKey: "pets.stylePixel" },
  { id: "chibi", labelKey: "pets.styleChibi" },
  { id: "plush", labelKey: "pets.stylePlush" },
  { id: "clay", labelKey: "pets.styleClay" },
  { id: "sticker", labelKey: "pets.styleSticker" },
  { id: "flat-vector", labelKey: "pets.styleFlatVector" },
  { id: "anime", labelKey: "pets.styleAnime" },
];

export function PetsSettingsPanel() {
  const { t } = useTranslation();
  const [pets, setPets] = useState<PetListItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>("builtin-crab");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [expanding, setExpanding] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [petName, setPetName] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  // AI generation state
  const [genPrompt, setGenPrompt] = useState("");
  const [genStyle, setGenStyle] = useState("pixel");
  const [actionPack, setActionPack] = useState("basic");
  const [generating, setGenerating] = useState(false);
  const [genJobId, setGenJobId] = useState<string | null>(null);
  const [genProgress, setGenProgress] = useState<GenerationProgress | null>(null);
  const progressEsRef = useRef<EventSource | null>(null);

  // Reference photo upload
  const [refPhoto, setRefPhoto] = useState<File | null>(null);
  const [refPhotoUrl, setRefPhotoUrl] = useState<string | null>(null);
  const [preserveReferenceStyle, setPreserveReferenceStyle] = useState(false);
  const refFileRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const [list, active] = await Promise.all([listPets(), getActivePet()]);
      const sorted = [
        { id: "builtin-crab", displayName: "CrabAgent 小螃蟹", description: "", is_builtin: true, created_at: "" },
        ...list.filter((p) => p.id !== "builtin-crab"),
      ];
      setPets(sorted);
      setActiveId(active || "builtin-crab");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to load pets");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  // On mount, check for in-progress generation jobs (the component may have
  // been unmounted by a tab switch while a job was running in the background).
  useEffect(() => {
    void (async () => {
      try {
        const jobs = await getActiveGenerations();
        if (jobs.length > 0) {
          // Pick the most recently updated job.
          const job = jobs.reduce((a, b) => (a.updated_at > b.updated_at ? a : b));
          setGenJobId(job.pet_id);
          setGenerating(true);
          setGenProgress({
            status: job.status as GenerationProgress["status"],
            step: job.step,
            total_steps: job.total_steps,
            step_name: job.step_name,
            step_label: job.step_label,
            prompt: job.prompt,
            style: job.style,
          });
        }
      } catch {
        // Non-critical — just no auto-reconnect.
      }
    })();
  }, []);

  // Subscribe to SSE progress when a job is active.
  useEffect(() => {
    if (!genJobId) return;
    const es = subscribeGenerationProgress(
      genJobId,
      (progress) => {
        setGenProgress(progress);
        if (progress.status === "done") {
          setGenJobId(null);
          setGenerating(false);
          setGenProgress(null);
          if (progressEsRef.current) {
            progressEsRef.current.close();
            progressEsRef.current = null;
          }
          void refresh();
          toast.success(t("pets.generated"));
        } else if (progress.status === "error") {
          setGenJobId(null);
          setGenerating(false);
          toast.error(progress.step_label || t("pets.generateFailed"));
          setGenProgress(null);
          if (progressEsRef.current) {
            progressEsRef.current.close();
            progressEsRef.current = null;
          }
        }
      },
      () => {
        // SSE error — fall back to polling status after a delay.
        setTimeout(async () => {
          try {
            const status = await getGenerationStatus(genJobId);
            if (status.status === "ready") {
              setGenJobId(null);
              setGenerating(false);
              setGenProgress(null);
              void refresh();
              toast.success(t("pets.generated", { name: status.displayName }));
            } else if (status.status === "error") {
              setGenJobId(null);
              setGenerating(false);
              setGenProgress(null);
              toast.error(status.description || t("pets.generateFailed"));
            }
          } catch {
            // keep waiting
          }
        }, 5000);
      },
    );
    progressEsRef.current = es;
    return () => {
      es.close();
      progressEsRef.current = null;
    };
  }, [genJobId, t]);

  const handleActivate = async (id: string) => {
    try {
      await setActivePet(id);
      localStorage.setItem("active_pet_id", id);
      setActiveId(id);
      toast.success(t("pets.activated"));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to activate");
    }
  };

  const handleRename = async (pet: PetListItem) => {
    const displayName = petName.trim();
    if (!displayName) return;
    try {
      await renamePet(pet.id, displayName);
      if (activeId === pet.id) window.dispatchEvent(new Event("active_pet_name_changed"));
      setRenamingId(null);
      await refresh();
      toast.success(t("pets.renamed"));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to rename pet");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t("pets.confirmDelete"))) return;
    try {
      await deletePet(id);
      if (activeId === id) {
        await setActivePet("builtin-crab");
        localStorage.setItem("active_pet_id", "builtin-crab");
        setActiveId("builtin-crab");
      }
      await refresh();
      toast.success(t("pets.deleted"));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to delete");
    }
  };

  const handleCreate = async () => {
    const id = prompt(t("pets.createPromptId"));
    if (!id) return;
    const displayName = prompt(t("pets.createPromptName"), id);
    if (!displayName) return;
    try {
      await createPet({ id, displayName, type: "spritesheet" });
      await refresh();
      toast.success(t("pets.created"));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to create");
    }
  };

  const handleGenerate = async () => {
    if (!genPrompt.trim()) return;
    setGenerating(true);
    setGenProgress(null);
    try {
      const resp = await generatePet(
        genPrompt.trim(),
        genStyle,
        refPhoto,
        preserveReferenceStyle,
        actionPack,
      );
      setGenJobId(resp.id);
      toast.info(t("pets.generateStarted"));
    } catch (e: unknown) {
      setGenerating(false);
      toast.error(e instanceof Error ? e.message : t("pets.generateFailed"));
    }
  };

  const handleExpand = async (petId: string, pack: "office" | "interactive") => {
    setExpanding(petId);
    try {
      const response = await expandPetActions(petId, pack);
      setGenJobId(response.id);
      setGenerating(true);
      toast.info(t("pets.expandStarted"));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t("pets.generateFailed"));
    } finally {
      setExpanding(null);
    }
  };

  const handleRefPhotoSelect = (file: File) => {
    setRefPhoto(file);
    if (refPhotoUrl) URL.revokeObjectURL(refPhotoUrl);
    setRefPhotoUrl(URL.createObjectURL(file));
  };

  const handleClearRefPhoto = () => {
    setRefPhoto(null);
    if (refPhotoUrl) URL.revokeObjectURL(refPhotoUrl);
    setRefPhotoUrl(null);
    if (refFileRef.current) refFileRef.current.value = "";
  };

  const handleFileSelect = async (petId: string, file: File) => {
    setUploading(petId);
    try {
      await uploadSpritesheet(petId, file);
      await refresh();
      toast.success(t("pets.uploaded"));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to upload");
    } finally {
      setUploading(null);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <p className="text-xs text-[var(--text-tertiary)]">{t("pets.description")}</p>
        <Button variant="secondary" size="sm" onClick={handleCreate}>
          <Cat size={14} className="mr-1.5" />
          {t("pets.create")}
        </Button>
      </div>

      {/* AI Generation section */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-tertiary)] p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-[var(--brand)]" />
          <span className="text-sm font-medium text-[var(--text-primary)]">{t("pets.aiGenerate")}</span>
        </div>
        <p className="text-xs text-[var(--text-tertiary)]">{t("pets.aiGenerateDesc")}</p>
        <Input
          value={genPrompt}
          onChange={(e) => setGenPrompt(e.target.value)}
          placeholder={t("pets.promptPlaceholder")}
          disabled={generating}
        />

        {/* Reference photo upload */}
        <div className="flex items-center gap-3">
          {refPhotoUrl ? (
            <div className="relative shrink-0">
              <img
                src={refPhotoUrl}
                alt="Reference"
                className="w-16 h-16 rounded-lg object-cover border border-[var(--border)]"
              />
              <button
                onClick={handleClearRefPhoto}
                disabled={generating}
                className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-[var(--danger)] text-white flex items-center justify-center text-xs hover:opacity-80"
              >
                <X size={12} />
              </button>
            </div>
          ) : (
            <button
              onClick={() => refFileRef.current?.click()}
              disabled={generating}
              className="shrink-0 w-16 h-16 rounded-lg border-2 border-dashed border-[var(--border)] flex flex-col items-center justify-center gap-1 text-[var(--text-tertiary)] hover:border-[var(--brand)] hover:text-[var(--brand)] transition-colors"
            >
              <ImageIcon size={18} />
              <span className="text-[9px]">{t("pets.uploadRef")}</span>
            </button>
          )}
          <div className="min-w-0 flex-1">
            <p className="text-xs text-[var(--text-tertiary)]">
              {refPhoto
                ? t("pets.refSelected")
                : t("pets.refHint")}
            </p>
          </div>
          <input
            ref={refFileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleRefPhotoSelect(file);
              e.target.value = "";
            }}
          />
        </div>
        {refPhoto && (
          <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] cursor-pointer select-none">
            <input
              type="checkbox"
              checked={preserveReferenceStyle}
              onChange={(e) => setPreserveReferenceStyle(e.target.checked)}
              disabled={generating}
              className="accent-[var(--brand)]"
            />
            {t("pets.preserveReferenceStyle")}
          </label>
        )}
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-[var(--text-secondary)]">{t("pets.actionPack")}</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {ACTION_PACKS.map((pack) => (
              <button
                key={pack.id}
                type="button"
                onClick={() => setActionPack(pack.id)}
                disabled={generating}
                className={cn(
                  "rounded-lg border px-2.5 py-2 text-left transition-colors",
                  actionPack === pack.id
                    ? "border-[var(--brand)] bg-[var(--brand)]/10"
                    : "border-[var(--border)] bg-[var(--bg-secondary)] hover:border-[var(--brand)]/50",
                )}
              >
                <span className="block text-xs font-medium text-[var(--text-primary)]">{t(pack.labelKey)}</span>
                <span className="block mt-0.5 text-[10px] leading-snug text-[var(--text-tertiary)]">{t(pack.descriptionKey)}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {PET_STYLES.map((s) => (
            <button
              key={s.id}
              onClick={() => setGenStyle(s.id)}
              disabled={generating}
              className={cn(
                "px-2.5 py-1 text-xs rounded-full transition-colors",
                genStyle === s.id
                  ? "bg-[var(--brand)] text-white"
                  : "bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
              )}
            >
              {t(s.labelKey)}
            </button>
          ))}
        </div>
        <Button
          variant="brand"
          size="sm"
          onClick={handleGenerate}
          disabled={!genPrompt.trim() || generating}
        >
          {generating ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              {t("pets.generating")}
            </>
          ) : (
            <>
              <Sparkles size={14} />
              {t("pets.generate")}
            </>
          )}
        </Button>

        {/* Live progress bar */}
        {generating && genProgress && (
          <div className="space-y-2 mt-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-[var(--text-secondary)]">{genProgress.step_label}</span>
              <span className="text-[var(--text-tertiary)] tabular-nums">
                {genProgress.step}/{genProgress.total_steps}
              </span>
            </div>
            <div className="h-2 rounded-full bg-[var(--bg-tertiary)] overflow-hidden">
              <div
                className="h-full bg-[var(--brand)] rounded-full transition-all duration-500 ease-out"
                style={{
                  width: genProgress.total_steps > 0
                    ? `${Math.min(100, (genProgress.step / genProgress.total_steps) * 100)}%`
                    : "0%",
                }}
              />
            </div>

          </div>
        )}

        {generating && !genProgress && (
          <p className="text-xs text-[var(--text-tertiary)]">{t("pets.generatingHint")}</p>
        )}
      </div>

      {/* Pet list */}
      {loading && (
        <div className="text-sm text-[var(--text-tertiary)]">{t("common.loading")}</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {pets.map((pet) => (
          <div
            key={pet.id}
            className={cn(
              "relative flex flex-col gap-2 p-3 rounded-xl border",
              activeId === pet.id
                ? "border-[var(--brand)] bg-[var(--brand)]/5"
                : "border-[var(--border)] bg-[var(--bg-secondary)]",
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                {renamingId === pet.id ? (
                  <form className="flex gap-1" onSubmit={(event) => { event.preventDefault(); void handleRename(pet); }}>
                    <Input
                      value={petName}
                      onChange={(event) => setPetName(event.target.value)}
                      maxLength={200}
                      autoFocus
                      className="h-8"
                    />
                    <Button variant="brand" size="xs" type="submit">{t("common.save")}</Button>
                  </form>
                ) : (
                  <div className="flex items-center gap-1">
                    <div className="font-medium text-sm text-[var(--text-primary)] truncate">{pet.displayName}</div>
                    {!pet.is_builtin && (
                      <button
                        type="button"
                        className="shrink-0 p-1 text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
                        onClick={() => { setRenamingId(pet.id); setPetName(pet.displayName); }}
                        title={t("pets.rename")}
                      >
                        <Pencil size={12} />
                      </button>
                    )}
                  </div>
                )}
                <div className="text-xs text-[var(--text-tertiary)] line-clamp-2">
                  {pet.description || (pet.is_builtin ? t("pets.builtin") : t("pets.custom"))}
                </div>
              </div>
              {activeId === pet.id && (
                <span className="shrink-0 inline-flex items-center justify-center w-5 h-5 rounded-full bg-[var(--brand)] text-white">
                  <Check size={12} />
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 mt-1">
              <Button
                variant={activeId === pet.id ? "brand" : "secondary"}
                size="sm"
                className="flex-1"
                onClick={() => handleActivate(pet.id)}
              >
                {activeId === pet.id ? t("pets.active") : t("pets.activate")}
              </Button>

              {!pet.is_builtin && (
                <>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={() => fileRef.current?.click()}
                    disabled={uploading === pet.id}
                    title={t("pets.uploadSpritesheet")}
                  >
                    <Upload size={14} />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-[var(--danger)] hover:text-[var(--danger)]"
                    onClick={() => handleDelete(pet.id)}
                    title={t("pets.delete")}
                  >
                    <Trash2 size={14} />
                  </Button>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".webp,.png"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void handleFileSelect(pet.id, file);
                      e.target.value = "";
                    }}
                  />
                </>
              )}
            </div>
            {!pet.is_builtin && (
              <Button
                variant="secondary"
                size="sm"
                className="w-full"
                disabled={expanding === pet.id || generating}
                onClick={() => void handleExpand(pet.id, "office")}
              >
                {expanding === pet.id ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                {t("pets.expandOffice")}
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}