import { AgentTeamPanel } from "../components/AgentTeamPanel";

export default function AgentsPage() {
  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      <AgentTeamPanel onClose={() => {}} inline />
    </div>
  );
}
