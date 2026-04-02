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

async function fetchReply(payload: ChatRequest): Promise<string> {
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
  return data.reply;
}

wsClient.connect();

wsClient.on("authenticated", () => {
  console.log("WeCom bot authenticated");
});

wsClient.on("error", (error: Error) => {
  console.error("WeCom bot error:", error.message);
});

wsClient.on("message.text", async (frame: WsFrame) => {
  const content = frame.body?.text?.content?.trim();
  if (!content) {
    return;
  }

  const payload: ChatRequest = {
    reqId: frame.headers?.req_id ?? "",
    msgId: frame.body?.msgid ?? "",
    chatId: frame.body?.chatid,
    userId: frame.body?.from?.userid ?? "",
    chatType: frame.body?.chattype ?? "single",
    content,
  };

  const streamId = generateReqId("stream");
  void tryReplyStream(frame, streamId, "Working on it...", false);

  try {
    const reply = await fetchReply(payload);
    const delivered = await tryReplyStream(frame, streamId, reply, true);
    if (!delivered) {
      console.error("Final reply was not acknowledged by WeCom");
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("Failed to process message:", message);
    await tryReplyStream(frame, streamId, `Request failed: ${message}`, true);
  }
});

wsClient.on("event.enter_chat", async (frame: WsFrame) => {
  await wsClient.replyWelcome(frame, {
    msgtype: "text",
    text: { content: "Hello, send me a message and I will forward it to the backend." },
  });
});

process.on("SIGINT", () => {
  wsClient.disconnect();
  process.exit(0);
});
