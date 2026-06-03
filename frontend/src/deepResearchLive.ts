/** In-memory deep research state (progress is never persisted to the server). */

export interface DeepResearchLiveState {
  messageId: string;
  progress: string;
  content: string;
  isComplete: boolean;
}

export type DeepResearchLivePatch = Partial<Omit<DeepResearchLiveState, "messageId">>;
