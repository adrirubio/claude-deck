import type { GithubIdentity } from "@/types/factory";
import { anchor } from "./styles";

function githubLink(
  identity: GithubIdentity,
  kind: "issues" | "pull",
  id: number,
) {
  if (
    !/^[A-Za-z0-9_.-]+$/.test(identity.owner) ||
    !/^[A-Za-z0-9_.-]+$/.test(identity.name) ||
    !Number.isSafeInteger(id) ||
    id <= 0
  )
    return null;
  return `https://github.com/${identity.owner}/${identity.name}/${kind}/${id}`;
}
export function GithubLink({
  identity,
  kind,
  id,
  children,
}: {
  identity: GithubIdentity;
  kind: "issues" | "pull";
  id: number;
  children: React.ReactNode;
}) {
  const href = githubLink(identity, kind, id);
  return href ? (
    <a className={anchor} href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ) : (
    <span>Invalid GitHub identity</span>
  );
}
