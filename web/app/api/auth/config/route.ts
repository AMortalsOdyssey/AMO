import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const apiKey = process.env.IDENTITY_PLATFORM_WEB_API_KEY || "";
  const authDomain = process.env.IDENTITY_PLATFORM_AUTH_DOMAIN || "";
  const projectId = process.env.IDENTITY_PLATFORM_PROJECT_ID || "";
  const appId = process.env.IDENTITY_PLATFORM_APP_ID || null;
  const messagingSenderId = process.env.IDENTITY_PLATFORM_MESSAGING_SENDER_ID || null;

  return NextResponse.json({
    enabled: Boolean(apiKey && authDomain && projectId),
    apiKey,
    authDomain,
    projectId,
    appId,
    messagingSenderId,
  });
}
