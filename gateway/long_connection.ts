import "dotenv/config";

import AiBot from "@wecom/aibot-node-sdk";
import type { WsFrame } from "@wecom/aibot-node-sdk";
import { generateReqId } from "@wecom/aibot-node-sdk";

type ChatRequest = {
  reqId: string;
  msgId: string;
  chatId?: string;
  userId: string;
  chatType: "single" | "group";
  content: string;
};

type ChatResponse = {
  reply: string;
  requestId?: string;
  attachment?: {
    type: "file";
    path: string;
    name: string;
  };
};

type UploadKnowledgeBaseResponse = {
  reply: string;
  fileName: string;
  action: "added" | "replaced" | "unchanged";
  knowledgeBasePath: string;
};

const botId = process.env.WECOM_BOT_ID;
const secret = process.env.WECOM_BOT_SECRET;
const backendBaseUrl = process.env.BACKEND_BASE_URL ?? "http://127.0.0.1:5000";

if (!botId || !secret) {
  throw new Error(
    "Missing WECOM_BOT_ID or WECOM_BOT_SECRET in environment. " +
      "Copy .env.example to .env and fill in the WeCom bot credentials.",
  );
}

const wsClient = new AiBot.WSClient({
  botId,
  secret,
});

// Per-session request queue: ensures messages from the same user are processed sequentially.
const sessionQueues = new Map<string, Promise<void>>();

function sessionKey(frame: WsFrame): string {
  const userId = frame.body?.from?.userid ?? "unknown";
  const chatId = frame.body?.chatid ?? "dm";
  return `${userId}:${chatId}`;
}

function enqueue(key: string, task: () => Promise<void>): void {
  const prev = sessionQueues.get(key) ?? Promise.resolve();
  const next = prev.then(task, task);
  sessionQueues.set(key, next);
  next.finally(() => {
    if (sessionQueues.get(key) === next) {
      sessionQueues.delete(key);
    }
  });
}

async function tryReplyStream(
  frame: WsFrame,
  streamId: string,
  content: string,
  finish: boolean,
): Promise<boolean> {
  try {
    await wsClient.replyStream(frame, streamId, content, finish);
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("replyStream failed:", message);
    return false;
  }
}

async function fetchReply(payload: ChatRequest): Promise<ChatResponse> {
  const response = await fetch(`${backendBaseUrl}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Backend request failed: ${response.status} ${text}`);
  }

  const data = (await response.json()) as ChatResponse;
  if (!data.reply) {
    throw new Error("Backend response did not contain reply");
  }
  return data;
}

function buildChatRequest(frame: WsFrame, content: string): ChatRequest {
  return {
    reqId: frame.headers?.req_id ?? "",
    msgId: frame.body?.msgid ?? "",
    chatId: frame.body?.chatid,
    userId: frame.body?.from?.userid ?? "",
    chatType: frame.body?.chattype ?? "single",
    content,
  };
}

async function uploadKnowledgeBasePdf(payload: ChatRequest, buffer: Buffer, filename: string): Promise<string> {
  const form = new FormData();
  form.append("reqId", payload.reqId);
  form.append("msgId", payload.msgId);
  if (payload.chatId) {
    form.append("chatId", payload.chatId);
  }
  form.append("userId", payload.userId);
  form.append("chatType", payload.chatType);
  form.append("file", new Blob([new Uint8Array(buffer)], { type: "application/pdf" }), filename);

  const response = await fetch(`${backendBaseUrl}/knowledge-base/upload`, {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Backend upload failed: ${response.status} ${text}`);
  }

  const data = (await response.json()) as UploadKnowledgeBaseResponse;
  if (!data.reply) {
    throw new Error("Backend upload response did not contain reply");
  }
  return data.reply;
}

wsClient.connect();
console.log(
  `[gateway] Connecting to WeCom bot=${botId.slice(0, 8)}... backend=${backendBaseUrl}`,
);

wsClient.on("authenticated", () => {
  console.log("[gateway] Authenticated and listening for messages");
});

wsClient.on("error", (error: Error) => {
  console.error("[gateway] Error:", error.message);
});

wsClient.on("message.text", async (frame: WsFrame) => {
  const content = frame.body?.text?.content?.trim();
  if (!content) {
    return;
  }

  const payload = buildChatRequest(frame, content);
  const streamId = generateReqId("stream");
  void tryReplyStream(frame, streamId, "Working on it...", false);
  console.log(`[gateway] ${payload.chatType}:${payload.userId} => ${content.slice(0, 80)}`);

  enqueue(sessionKey(frame), async () => {
    try {
      const result = await fetchReply(payload);
      const delivered = await tryReplyStream(frame, streamId, result.reply, true);
      if (!delivered) {
        console.error("[gateway] Final reply was not acknowledged by WeCom");
      }

      if (result.attachment?.type === "file") {
        const filePath = result.attachment.path;
        const fileName = result.attachment.name;
        const fileBuffer = Buffer.from(await (await import("fs/promises")).readFile(filePath));
        const uploadResult = await wsClient.uploadMedia(fileBuffer, {
          type: "file",
          filename: fileName,
        });
        await wsClient.replyMedia(frame, "file", uploadResult.media_id);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error("[gateway] Failed to process message:", message);
      await tryReplyStream(frame, streamId, `Request failed: ${message}`, true);
    }
  });
});

wsClient.on("message.file", async (frame: WsFrame) => {
  const fileUrl = frame.body?.file?.url;
  const aesKey = frame.body?.file?.aeskey;
  if (!fileUrl) {
    return;
  }

  const payload = buildChatRequest(frame, `[上传文件] ${frame.body?.msgid ?? ""}`);
  const streamId = generateReqId("stream");
  void tryReplyStream(frame, streamId, "Receiving PDF...", false);
  console.log(`[gateway] File upload from ${payload.userId}`);

  enqueue(sessionKey(frame), async () => {
    try {
      const { buffer, filename } = await wsClient.downloadFile(fileUrl, aesKey);
      const resolvedName = (filename ?? `${payload.msgId || "uploaded"}.pdf`).trim();
      if (!resolvedName.toLowerCase().endsWith(".pdf")) {
        throw new Error("Only PDF files can be added to the knowledge base");
      }

      const reply = await uploadKnowledgeBasePdf(payload, buffer, resolvedName);
      const delivered = await tryReplyStream(frame, streamId, reply, true);
      if (!delivered) {
        console.error("[gateway] Upload reply was not acknowledged by WeCom");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error("[gateway] Failed to process file message:", message);
      await tryReplyStream(frame, streamId, `Request failed: ${message}`, true);
    }
  });
});

wsClient.on("event.enter_chat", async (frame: WsFrame) => {
  const userId = frame.body?.from?.userid ?? "unknown";
  console.log(`[gateway] enter_chat event from ${userId}`);
  try {
    await wsClient.replyWelcome(frame, {
      msgtype: "text",
      text: { content: "您好~请问您想要我为您做什么呀？" },
    });
    console.log(`[gateway] Welcome message sent to ${userId}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[gateway] Failed to send welcome: ${message}`);
  }
});

process.on("SIGINT", () => {
  wsClient.disconnect();
  process.exit(0);
});
