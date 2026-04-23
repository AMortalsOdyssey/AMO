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

  // 转发认证头
  const authHeader = request.headers.get("Authorization");
  if (authHeader) {
    headers.set("Authorization", authHeader);
  }

  const acceptHeader = request.headers.get("Accept");
  if (acceptHeader) {
    headers.set("Accept", acceptHeader);
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
    const headers = new Headers();
    const contentType = response.headers.get("Content-Type");
    if (contentType) {
      headers.set("Content-Type", contentType);
    }
    const xAccelBuffering = response.headers.get("X-Accel-Buffering");
    if (xAccelBuffering) {
      headers.set("X-Accel-Buffering", xAccelBuffering);
    }
    headers.set("Cache-Control", "no-store, max-age=0");

    const isSse = contentType?.startsWith("text/event-stream");
    if (isSse) {
      headers.set("Cache-Control", "no-cache, no-store, max-age=0");
      headers.set("Connection", "keep-alive");
      headers.set("X-Accel-Buffering", "no");
      return new Response(response.body, {
        status: response.status,
        headers,
      });
    }

    return NextResponse.json(
      await response.json(),
      {
        status: response.status,
        headers,
      }
    );
  } catch (error) {
    console.error(`Proxy error: ${url}`, error);
    return NextResponse.json(
      { error: "Backend service unavailable" },
      { status: 502 }
    );
  }
}
