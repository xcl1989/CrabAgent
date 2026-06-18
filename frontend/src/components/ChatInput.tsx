import { useState, useRef, useCallback } from "react";
import { ArrowUp, Square, Paperclip, Bot } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button, Textarea } from "./ui";

interface Props {
  sending: boolean;
  replaying: boolean;
  onSend: (text: string) => void;
  onAbort: () => void;
  onFileUpload: () => void;
  onFilePaste: (e: React.ClipboardEvent) => void;
  onDelegateOpen: () => void;
  showDelegate?: boolean;
}

export default function ChatInput({
  sending,
  replaying,
  onSend,
  onAbort,
  onFileUpload,
  onFilePaste,
  onDelegateOpen,
  showDelegate,
}: Props) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text) return;
    onSend(text);
    setInput("");
  }, [input, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <>
      <Button
        size="icon"
        variant="outline"
        onClick={onFileUpload}
        disabled={sending || replaying}
        title={t("chat.attachFile")}
        className="h-9 w-9 sm:h-10 sm:w-10"
      >
        <Paperclip size={15} />
      </Button>
      {showDelegate && (
        <Button
          size="icon"
          variant="outline"
          onClick={onDelegateOpen}
          disabled={sending || replaying}
          title={t("chat.delegate")}
          className="hidden sm:flex h-10 w-10 text-[var(--accent-2)] hover:text-[var(--accent-2)] hover:bg-[var(--accent-2-bg)] border-[var(--border)]"
        >
          <Bot size={15} />
        </Button>
      )}
      <Textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={onFilePaste}
        placeholder={t("chat.placeholder")}
        disabled={sending || replaying}
        ref={inputRef}
        autoGrow
        minRows={1}
        maxRows={6}
        className="flex-1 min-h-[36px] sm:min-h-[40px]"
      />
      {sending ? (
        <Button
          variant="danger"
          onClick={onAbort}
          className="h-9 w-9 sm:h-10 sm:w-10"
          size="icon"
          title={t("common.stop")}
        >
          <Square size={14} fill="currentColor" />
        </Button>
      ) : (
        <Button
          variant="brand"
          onClick={handleSend}
          disabled={!input.trim()}
          className="h-9 w-9 sm:h-10 sm:w-10 shrink-0"
          size="icon"
          title={t("common.send")}
        >
          <ArrowUp size={16} />
        </Button>
      )}
    </>
  );
}
