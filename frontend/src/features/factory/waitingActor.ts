// #513: the plain name of who a work item waits for. The API value `operator`
// stays in the data; people read Director.
export function waitingActorLabel(actor: string): string {
  if (actor === "leader") return "Leader";
  if (actor === "operator") return "Director";
  return actor;
}
