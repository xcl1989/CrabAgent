import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Upload, Trash2, Check, Cat, Sparkles, Loader2, ImageIcon, X } from "lucide-react";
import { Button, Input } from "./ui";
import { toast } from "./ui/Toast";
import { cn } from "../lib/cn";
import {
  createPet,
  deletePet,
  generatePet,
  getActivePet,
  getGenerationStatus,
  getPet,
  listPets,
  setActivePet,
  subscribeGenerationProgress,
  uploadSpritesheet,
  type GenerationProgress,
  type PetListItem,
} from "../api/pets";

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
  const fileRef = useRef<HTMLInputElement>(null);

  // AI generation state
  const [genPrompt, setGenPrompt] = useState("");
  const [genStyle, setGenStyle] = useState("pixel");
  const [generating, setGenerating] = useState(false);
  const [genJobId, setGenJobId] = useState<string | null>(null);
  const [genProgress, setGenProgress] = useState<GenerationProgress | null>(null);
  const progressEsRef = useRef<EventSource | null>(null);

  // Reference photo upload
  const [refPhoto, setRefPhoto] = useState<File | null>(null);
  const [refPhotoUrl, setRefPhotoUrl] = useState<string | null>(null);
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
      const resp = await generatePet(genPrompt.trim(), genStyle, refPhoto);
      setGenJobId(resp.id);
      toast.info(t("pets.generateStarted"));
    } catch (e: unknown) {
      setGenerating(false);
      toast.error(e instanceof Error ? e.message : t("pets.generateFailed"));
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
            {/* Step list */}
            <div className="flex flex-wrap gap-1 mt-1">
              {[
                { label: "参考图", step: 1 },
                { label: "待机", step: 2 },
                { label: "跑→", step: 3 },
                { label: "跑←", step: 4 },
                { label: "挥手", step: 5 },
                { label: "跳跃", step: 6 },
                { label: "失败", step: 7 },
                { label: "等待", step: 8 },
                { label: "工作", step: 9 },
                { label: "完成", step: 10 },
                { label: "合成", step: 11 },
                { label: "保存", step: 12 },
              ].map((s) => (
                <span
                  key={s.step}
                  className={cn(
                    "px-1.5 py-0.5 text-[10px] rounded transition-colors",
                    genProgress.step > s.step
                      ? "bg-[var(--success)]/20 text-[var(--success)]"
                      : genProgress.step === s.step
                        ? "bg-[var(--brand)]/20 text-[var(--brand)]"
                        : "bg-[var(--bg-tertiary)] text-[var(--text-tertiary)]",
                  )}
                >
                  {genProgress.step > s.step ? "✓ " : ""}
                  {s.label}
                </span>
              ))}
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
              <div className="min-w-0">
                <div className="font-medium text-sm text-[var(--text-primary)] truncate">
                  {pet.displayName}
                </div>
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
          </div>
        ))}
      </div>
    </div>
  );
}