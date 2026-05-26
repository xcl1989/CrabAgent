import { useCallback, useState } from "react";
import { SSEEvent } from "../api/events";
import { TaskInfo } from "../components/TaskBoard.types";

export function useTaskBoard() {
  const [taskBoardTasks, setTaskBoardTasks] = useState<TaskInfo[]>([]);

  const handleTaskBoardEvent = useCallback((event: SSEEvent) => {
    if (event.type === "sub_agent_start") {
      const subId = (event.data.sub_agent_id as string) || "";
      const name = (event.data.agent_name as string) || "";
      setTaskBoardTasks((prev) => {
        if (prev.some((t) => t.subId === subId)) return prev;
        return [
          ...prev,
          {
            subId,
            agentName: name,
            displayName: (event.data.display_name as string) || name,
            icon: "",
            status: "running" as const,
            task: (event.data.task as string) || "",
            content: "",
            toolCalls: 0,
            startedAt: Date.now(),
          },
        ];
      });
    }

    if (event.type === "sub_agent_tool_call") {
      const subId = (event.data.sub_agent_id as string) || "";
      setTaskBoardTasks((prev) => prev.map((t) => (t.subId === subId ? { ...t, toolCalls: t.toolCalls + 1 } : t)));
    }

    if (event.type === "sub_agent_end") {
      const subId = (event.data.sub_agent_id as string) || "";
      setTaskBoardTasks((prev) =>
        prev.map((t) =>
          t.subId === subId
            ? {
                ...t,
                status: "done" as const,
                content: (event.data.result as string) || t.content,
                elapsed: event.data.elapsed as number,
                tokens: event.data.tokens as number,
                iterations: event.data.iterations as number,
              }
            : t
        )
      );
    }

    if (event.type === "sub_agent_error") {
      const subId = (event.data.sub_agent_id as string) || "";
      setTaskBoardTasks((prev) =>
        prev.map((t) =>
          t.subId === subId ? { ...t, status: "error" as const, error: (event.data.error as string) || "Unknown error" } : t
        )
      );
    }
  }, []);

  const clearTaskBoard = useCallback(() => setTaskBoardTasks([]), []);

  return { taskBoardTasks, handleTaskBoardEvent, clearTaskBoard };
}
