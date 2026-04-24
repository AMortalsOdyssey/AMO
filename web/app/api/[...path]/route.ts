import { NextRequest, NextResponse } from "next/server";

// 运行时环境变量，从 K8s ConfigMap 注入
// 例如: http://amo-server.amo.svc.cluster.local:8100/api
const API_BASE = process.env.API_BASE || "http://localhost:8100/api";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, await params);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, await params);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, await params);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(request, await params);
}

async function proxyRequest(
  request: NextRequest,
  params: { path: string[] }
) {
  const path = params.path.join("/");
  const url = `${API_BASE}/${path}${request.nextUrl.search}`;

  const headers = new Headers();
  for (const [key, value] of request.headers.entries()) {
    const normalized = key.toLowerCase();
    if (normalized === "host" || normalized === "content-length" || normalized === "connection") {
      continue;
    }
    if (
      normalized === "authorization" ||
      normalized === "accept" ||
      normalized === "content-type" ||
      normalized === "cookie" ||
      normalized.startsWith("x-amo-") ||
      normalized.startsWith("x-request-")
    ) {
      headers.set(key, value);
    }
  }

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: "no-store",
  };

  // 转发请求体
  if (request.method !== "GET" && request.method !== "HEAD") {
    try {
      headers.set("Content-Type", request.headers.get("Content-Type") || "application/json");
      init.body = await request.text();
    } catch {
      // 无请求体
    }
  }

  try {
    const response = await fetch(url, init);
    const responseHeaders = new Headers();
    const contentType = response.headers.get("Content-Type");
    if (contentType) {
      responseHeaders.set("Content-Type", contentType);
    }
    const xAccelBuffering = response.headers.get("X-Accel-Buffering");
    if (xAccelBuffering) {
      responseHeaders.set("X-Accel-Buffering", xAccelBuffering);
    }
    const setCookieHeaders =
      typeof (response.headers as Headers & { getSetCookie?: () => string[] }).getSetCookie === "function"
        ? (response.headers as Headers & { getSetCookie: () => string[] }).getSetCookie()
        : [];
    if (setCookieHeaders.length > 0) {
      for (const setCookieHeader of setCookieHeaders) {
        responseHeaders.append("Set-Cookie", setCookieHeader);
      }
    } else {
      const singleSetCookieHeader = response.headers.get("set-cookie");
      if (singleSetCookieHeader) {
        responseHeaders.append("Set-Cookie", singleSetCookieHeader);
      }
    }
    responseHeaders.set("Cache-Control", "no-store, max-age=0");

    const isSse = contentType?.startsWith("text/event-stream");
    if (isSse) {
      responseHeaders.set("Cache-Control", "no-cache, no-store, max-age=0");
      responseHeaders.set("Connection", "keep-alive");
      responseHeaders.set("X-Accel-Buffering", "no");
      return new Response(response.body, {
        status: response.status,
        headers: responseHeaders,
      });
    }

    if (response.status === 204) {
      return new Response(null, {
        status: response.status,
        headers: responseHeaders,
      });
    }

    if (contentType?.includes("application/json")) {
      return NextResponse.json(
        await response.json(),
        {
          status: response.status,
          headers: responseHeaders,
        }
      );
    }

    return new Response(await response.text(), {
      status: response.status,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error(`Proxy error: ${url}`, error);
    return NextResponse.json(
      { error: "Backend service unavailable" },
      { status: 502 }
    );
  }
}
