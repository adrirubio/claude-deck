import { useParams } from "react-router-dom";
import type { RepositoryDetailResponse } from "@/types/factory";
import { ReadStatus } from "../components/ReadStatus";
import { RepositoryCard } from "../components/RepositoryCard";
import { Time } from "../components/Time";
import { WorkResults } from "../components/WorkResults";
import { useObservation } from "../reads";

export function RepositoryPage() {
  const { scopeId } = useParams();
  const state = useObservation<RepositoryDetailResponse>(
    `factory/repositories/${encodeURIComponent(scopeId ?? "")}`,
  );
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">
        {state.data ? `Repository scope ${scopeId}` : "Repository"}
      </h2>
      <ReadStatus
        state={state}
        back={{ to: "/repositories", label: "Back to Repositories" }}
        missing="repository"
      />
      {state.data && (
        <>
          <RepositoryCard repository={state.data.repository} />
          <Time value={state.data.generated_at} />
          <h3 className="text-lg font-semibold">Scope work</h3>
          <WorkResults
            key={scopeId}
            query={`scope_id=${encodeURIComponent(scopeId ?? "")}`}
          />
        </>
      )}
    </section>
  );
}
