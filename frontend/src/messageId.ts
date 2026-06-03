let counter = 0;

export function generateMessageId(): string {
  return `msg-${Date.now()}-${++counter}`;
}
