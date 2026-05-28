import { useNavigate } from "react-router-dom";
import { AgentTeamPanel } from "../components/AgentTeamPanel";

export default function AgentsPage() {
  const navigate = useNavigate();
  return (
    <div className="flex-1 overflow-auto">
      <AgentTeamPanel onClose={() => navigate("/chat")} />
    </div>
  );
}
