export type Message = {
  id?: string;
  role: "user" | "assistant";
  content: string;
};

export type Conversation = {
  sessionId: string;
  title: string;
};

export type ChatResponse = {
  session_id: string;
  answer: string;
};

export type SessionMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export type SessionResponse = {
  messages: SessionMessage[];
};

export type ApiSession = {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
};

export type SessionsResponse = {
  sessions: ApiSession[];
};