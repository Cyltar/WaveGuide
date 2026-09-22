import { createClient } from "@/lib/supabase/client";

import type {
  ChatResponse,
  SessionResponse,
  SessionsResponse,
} from "@/types/chat";


const API_URL = process.env.NEXT_PUBLIC_API_URL;


export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(
    message: string,
    status: number,
    code?: string
  ) {
    super(message);

    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}


async function getAccessToken(): Promise<string> {
  const supabase = createClient();

  const {
    data: { session },
    error,
  } = await supabase.auth.getSession();

  if (error) {
    throw new ApiError(
      error.message,
      401,
      "UNAUTHORIZED"
    );
  }

  if (!session) {
    throw new ApiError(
      "You must be signed in to use LoLGPT.",
      401,
      "UNAUTHORIZED"
    );
  }

  return session.access_token;
}


async function handleApiError(
  response: Response
): Promise<never> {
  let message = "Something went wrong.";
  let code: string | undefined;

  try {
    const data = await response.json();

    if (
      typeof data.detail === "object"
      && data.detail !== null
    ) {
      message =
        data.detail.message
        ?? message;

      code =
        data.detail.code
        ?? undefined;
    } else if (
      typeof data.detail === "string"
    ) {
      message = data.detail;
    }
  } catch {
    // Response was not JSON.
  }

  throw new ApiError(
    message,
    response.status,
    code
  );
}


export async function sendMessage(
  message: string,
  sessionId: string | null
): Promise<ChatResponse> {
  const accessToken =
    await getAccessToken();

  const response = await fetch(
    `${API_URL}/chat`,
    {
      method: "POST",

      headers: {
        "Content-Type":
          "application/json",

        Authorization:
          `Bearer ${accessToken}`,
      },

      body: JSON.stringify({
        message,
        session_id: sessionId,
      }),
    }
  );

  if (!response.ok) {
    return handleApiError(response);
  }

  return response.json();
}


export async function getSessions(): Promise<SessionsResponse> {
  const accessToken =
    await getAccessToken();

  const response = await fetch(
    `${API_URL}/sessions`,
    {
      method: "GET",

      headers: {
        Authorization:
          `Bearer ${accessToken}`,
      },
    }
  );

  if (!response.ok) {
    return handleApiError(response);
  }

  return response.json();
}


export async function getSession(
  sessionId: string
): Promise<SessionResponse> {
  const accessToken =
    await getAccessToken();

  const response = await fetch(
    `${API_URL}/sessions/${sessionId}`,
    {
      method: "GET",

      headers: {
        Authorization:
          `Bearer ${accessToken}`,
      },
    }
  );

  if (!response.ok) {
    return handleApiError(response);
  }

  return response.json();
}

export async function deleteAccount(): Promise<void> {
  const accessToken = await getAccessToken();
  const response = await fetch(`${API_URL}/account`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) {
    throw new ApiError("Unable to delete your account. Please try again.", response.status, "ACCOUNT_DELETION_FAILED");
  }
  const result = await response.json();
  if (result.deleted !== true) {
    throw new ApiError("Unable to confirm account deletion. Please try again.", 502, "ACCOUNT_DELETION_FAILED");
  }
}
