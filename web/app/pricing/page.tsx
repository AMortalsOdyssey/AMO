"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, startTransition, useEffect, useState } from "react";
import {
  apiFetch,
  type BillingCatalog,
  type BillingCheckout,
  type BillingCheckoutDetail,
} from "@/lib/api";
import { captureEvent } from "@/lib/analytics";

function formatPrice(cents: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(cents / 100);
}

function PricingInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [catalog, setCatalog] = useState<BillingCatalog | null>(null);
  const [checkoutDetail, setCheckoutDetail] = useState<BillingCheckoutDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [creatingCheckout, setCreatingCheckout] = useState(false);
  const [resolvingMock, setResolvingMock] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkoutRequestId = searchParams.get("checkout_request_id");
  const mockCheckoutRequestId = searchParams.get("mock_checkout_request_id");
  const paymentState = searchParams.get("payment");
  const activeRequestId = mockCheckoutRequestId || checkoutRequestId;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    apiFetch<BillingCatalog>("/billing/catalog")
      .then((data) => {
        if (!cancelled) {
          setCatalog(data);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load pricing.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!activeRequestId) {
      setCheckoutDetail(null);
      return;
    }

    let cancelled = false;
    apiFetch<BillingCheckoutDetail>(`/billing/checkouts/${activeRequestId}`)
      .then((data) => {
        if (!cancelled) {
          setCheckoutDetail(data);
          setCatalog((prev) => (prev ? { ...prev, summary: data.summary } : prev));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCheckoutDetail(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeRequestId]);

  const startCheckout = async () => {
    setCreatingCheckout(true);
    setError(null);

    try {
      const checkout = await apiFetch<BillingCheckout>("/billing/checkouts", {
        method: "POST",
        body: JSON.stringify({}),
      });

      captureEvent("pricing_checkout_started", {
        mode: checkout.mode,
        request_id: checkout.request_id,
        amount_cents: checkout.amount_cents,
      });

      if (checkout.checkout_url) {
        window.location.href = checkout.checkout_url;
        return;
      }

      startTransition(() => {
        router.push(`/pricing?mock_checkout_request_id=${checkout.request_id}`);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create checkout.");
    } finally {
      setCreatingCheckout(false);
    }
  };

  const resolveMockCheckout = async (outcome: "success" | "cancel") => {
    if (!mockCheckoutRequestId) {
      return;
    }

    setResolvingMock(true);
    setError(null);

    try {
      const detail = await apiFetch<BillingCheckoutDetail>(
        `/billing/checkouts/${mockCheckoutRequestId}/mock-complete`,
        {
          method: "POST",
          body: JSON.stringify({ outcome }),
        }
      );

      setCheckoutDetail(detail);
      setCatalog((prev) => (prev ? { ...prev, summary: detail.summary } : prev));

      captureEvent("pricing_mock_checkout_completed", {
        outcome,
        request_id: mockCheckoutRequestId,
      });

      const params = new URLSearchParams();
      params.set("payment", outcome === "success" ? "success" : "canceled");
      params.set("checkout_request_id", mockCheckoutRequestId);

      startTransition(() => {
        router.replace(`/pricing?${params.toString()}`);
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve mock checkout.");
    } finally {
      setResolvingMock(false);
    }
  };

  const currentSummary = checkoutDetail?.summary || catalog?.summary || null;
  const pack = catalog?.pack;
  const paymentModeLabel = catalog?.mode === "local_mock" ? "Local Mock" : "Creem Test";

  return (
    <div className="relative mx-auto max-w-6xl px-4 py-10 md:py-14">
      <div className="pointer-events-none absolute left-[-4rem] top-8 h-52 w-52 rounded-full bg-emerald-200/8 blur-3xl" />
      <div className="pointer-events-none absolute right-[-2rem] top-28 h-56 w-56 rounded-full bg-cyan-200/8 blur-3xl" />

      <section className="mb-8">
        <div className="amo-panel mx-auto overflow-hidden rounded-[2rem] p-6 md:p-8">
          <div className="grid gap-6 md:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] md:items-end">
            <div>
              <div className="amo-kicker inline-flex rounded-full px-3 py-1 text-xs uppercase tracking-[0.22em]">
                Pricing
              </div>
              <h1 className="amo-title-gradient mt-4 text-4xl font-semibold tracking-[0.12em] md:text-5xl">
                对话额度与支付
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-7 text-white/64 md:text-base">
                AMO 当前采用最小单体内嵌支付方案。每个浏览器会先获得 100 次免费对话额度，之后可按
                {pack ? ` ${formatPrice(pack.price_cents, pack.currency)} / ${pack.credits_per_unit} 次` : " 100 次 / $1"}
                的方式补充。
              </p>
            </div>

            <div className="amo-panel-strong rounded-[1.6rem] p-5">
              <div className="text-xs uppercase tracking-[0.24em] text-white/38">Current Balance</div>
              <div className="mt-3 text-4xl font-semibold text-white/94">
                {currentSummary ? currentSummary.remaining_credits : loading ? "..." : "0"}
              </div>
              <div className="mt-2 text-sm text-white/58">
                剩余对话次数
                {currentSummary ? ` · 免费剩余 ${currentSummary.free_credits_remaining}` : ""}
              </div>
              <div className="mt-5 flex flex-wrap gap-2 text-xs text-white/44">
                <span className="rounded-full border border-white/8 bg-white/4 px-3 py-1">
                  Mode · {paymentModeLabel}
                </span>
                <span className="rounded-full border border-white/8 bg-white/4 px-3 py-1">
                  Provider · Creem
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {error ? (
        <div className="mb-6 rounded-2xl border border-rose-300/20 bg-rose-300/10 px-4 py-3 text-sm text-rose-100">
          {error}
        </div>
      ) : null}

      {mockCheckoutRequestId ? (
        <section className="mb-6">
          <div className="amo-panel-strong rounded-[1.8rem] border border-emerald-200/18 p-5">
            <div className="text-xs uppercase tracking-[0.22em] text-emerald-200/70">Mock Checkout</div>
            <div className="mt-3 text-xl font-semibold text-white/92">模拟一笔 $1 的 Creem 测试支付</div>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-white/62">
              这个分支专门给现在的 demo 联调使用。它会走和正式接入一致的本地创建订单、完成支付、发放额度
              流程，但不要求你先拥有真实的 Creem 测试账号。
            </p>
            <div className="mt-5 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => resolveMockCheckout("success")}
                disabled={resolvingMock}
                className="amo-button-primary rounded-xl px-5 py-2.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                {resolvingMock ? "处理中..." : "模拟支付成功"}
              </button>
              <button
                type="button"
                onClick={() => resolveMockCheckout("cancel")}
                disabled={resolvingMock}
                className="amo-button-secondary rounded-xl px-5 py-2.5 text-sm disabled:cursor-not-allowed disabled:opacity-50"
              >
                模拟取消
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {paymentState === "success" && checkoutDetail?.checkout.status === "completed" ? (
        <section className="mb-6">
          <div className="rounded-2xl border border-emerald-200/18 bg-emerald-200/10 px-4 py-3 text-sm text-emerald-50">
            支付完成，额度已到账。当前剩余 {checkoutDetail.summary.remaining_credits} 次对话。
          </div>
        </section>
      ) : null}

      {paymentState === "canceled" ? (
        <section className="mb-6">
          <div className="rounded-2xl border border-white/8 bg-white/4 px-4 py-3 text-sm text-white/66">
            这笔测试支付已取消，没有扣费，也没有增加额度。
          </div>
        </section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
        <section className="amo-panel amo-panel-interactive rounded-[1.8rem] p-6">
          <div className="text-xs uppercase tracking-[0.22em] text-white/38">Free Allowance</div>
          <h2 className="mt-3 text-2xl font-semibold text-white/92">启动即送 100 次</h2>
          <p className="mt-3 text-sm leading-6 text-white/64">
            当前浏览器首次进入 AMO 时，会自动获得 100 次免费对话额度，用于测试角色对话体验。
          </p>
          <div className="mt-6 rounded-2xl border border-white/8 bg-white/4 p-4">
            <div className="text-3xl font-semibold text-white/92">{catalog?.free_allowance_credits ?? 100}</div>
            <div className="mt-1 text-xs uppercase tracking-[0.22em] text-white/34">Free Dialogue Credits</div>
          </div>
          <p className="mt-4 text-xs leading-6 text-white/44">
            Demo 阶段按浏览器 token 识别用户，后续接入 Google 登录后会切到正式账号体系。
          </p>
        </section>

        <section className="amo-panel amo-panel-interactive rounded-[1.8rem] p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.22em] text-white/38">Top-Up Pack</div>
              <h2 className="mt-3 text-2xl font-semibold text-white/92">{pack?.display_name || "100 次加购包"}</h2>
            </div>
            <div className="rounded-full border border-emerald-200/18 bg-emerald-200/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-emerald-100">
              One-Time
            </div>
          </div>

          <div className="mt-6 flex items-end gap-3">
            <div className="text-4xl font-semibold text-white/94">
              {pack ? formatPrice(pack.price_cents, pack.currency) : "$1.00"}
            </div>
            <div className="pb-1 text-sm text-white/48">
              / {pack?.credits_per_unit ?? 100} 次对话
            </div>
          </div>

          <p className="mt-4 text-sm leading-6 text-white/64">
            这是当前唯一的付费商品。支付完成后立即补充对话额度，不走订阅，也不会自动续费。
          </p>

          <button
            type="button"
            onClick={startCheckout}
            disabled={creatingCheckout || !pack?.is_active}
            className="amo-button-primary mt-6 w-full rounded-2xl py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          >
            {creatingCheckout
              ? "创建结账中..."
              : catalog?.mode === "local_mock"
                ? "开始 Mock 支付测试"
                : "前往 Creem Test Checkout"}
          </button>

          <div className="mt-4 flex flex-wrap gap-2 text-xs text-white/44">
            <span className="rounded-full border border-white/8 bg-white/4 px-3 py-1">
              Currency · {pack?.currency || "USD"}
            </span>
            <span className="rounded-full border border-white/8 bg-white/4 px-3 py-1">
              Credits · {pack?.credits_per_unit || 100}
            </span>
          </div>
        </section>

        <section className="amo-panel rounded-[1.8rem] p-6">
          <div className="text-xs uppercase tracking-[0.22em] text-white/38">Config Snapshot</div>
          <div className="mt-5 space-y-4 text-sm">
            <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
              <div className="text-white/42">商品 Key</div>
              <div className="mt-1 font-medium text-white/88">{pack?.product_key || "chat-pack-100"}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
              <div className="text-white/42">结账模式</div>
              <div className="mt-1 font-medium text-white/88">{paymentModeLabel}</div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
              <div className="text-white/42">Creem 商品配置</div>
              <div className="mt-1 font-medium text-white/88">
                {pack?.creem_product_id_configured ? "已配置" : "未配置，当前走本地 Mock"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
              <div className="text-white/42">支持邮箱</div>
              <div className="mt-1 font-medium text-white/88">{catalog?.support_email || "support@8xd.io"}</div>
            </div>
          </div>

          <div className="mt-5 text-xs leading-6 text-white/42">
            商品管理接口已内置在后端：`GET /billing/catalog` 与 `PUT /billing/products/chat-pack-100`。
            现在还没有后台 UI，先用接口管理配置会更轻。
          </div>
        </section>
      </div>

      <section className="mt-8 grid gap-4 md:grid-cols-2">
        <div className="amo-panel rounded-[1.8rem] p-6">
          <div className="text-xs uppercase tracking-[0.22em] text-white/38">What Gets Counted</div>
          <div className="mt-4 space-y-3 text-sm leading-6 text-white/64">
            <p>当前版本先对角色对话接口扣减额度，每次发送一条消息计 1 次。</p>
            <p>语音对话未来可以直接复用同一额度账本，不需要重写支付逻辑。</p>
          </div>
        </div>

        <div className="amo-panel rounded-[1.8rem] p-6">
          <div className="text-xs uppercase tracking-[0.22em] text-white/38">Next Step</div>
          <div className="mt-4 space-y-3 text-sm leading-6 text-white/64">
            <p>
              现在可以直接去 <Link href="/chat" className="text-emerald-200 hover:text-emerald-100">角色对话</Link>
              页面测试额度扣减；额度不足时会自动提示回到 Pricing。
            </p>
            <p>等你拿到真实的 Creem 测试产品 ID 和 API Key，我只需要把模式从 Local Mock 切到 Creem Test 即可。</p>
          </div>
        </div>
      </section>
    </div>
  );
}

export default function PricingPage() {
  return (
    <Suspense fallback={<div className="p-8 text-white/48">加载中...</div>}>
      <PricingInner />
    </Suspense>
  );
}
