"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  apiFetch,
  type BillingCatalog,
  type BillingCheckout,
  type BillingCheckoutDetail,
} from "@/lib/api";
import { captureEvent } from "@/lib/analytics";
import { useAuthSession } from "@/components/AuthProvider";

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
  const { session, loading: authLoading } = useAuthSession();
  const [catalog, setCatalog] = useState<BillingCatalog | null>(null);
  const [checkoutDetail, setCheckoutDetail] = useState<BillingCheckoutDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [creatingCheckout, setCreatingCheckout] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkoutRequestId = searchParams.get("checkout_request_id");
  const paymentState = searchParams.get("payment");
  const activeRequestId = checkoutRequestId;

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

  const currentSummary = checkoutDetail?.summary || catalog?.summary || null;
  const pack = catalog?.pack;
  const paymentsReady = Boolean(pack?.is_active && catalog && catalog.mode !== "local_mock");
  const canStartCheckout = paymentsReady && !authLoading;

  const startCheckout = async () => {
    if (!paymentsReady) {
      setError("支付通道即将开放。你仍然可以继续使用当前免费额度。");
      return;
    }
    if (!session.authenticated) {
      router.push(`/auth?next=${encodeURIComponent("/pricing")}`);
      return;
    }

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

      throw new Error("暂时无法打开支付页面，请稍后再试。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create checkout.");
    } finally {
      setCreatingCheckout(false);
    }
  };

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
                每个浏览器会自动获得免费对话额度。需要更多角色对话时，可以按
                {pack ? ` ${formatPrice(pack.price_cents, pack.currency)} / ${pack.credits_per_unit} 次` : " 1000 次 / $1"}
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
                  角色对话可用
                </span>
                <span className="rounded-full border border-white/8 bg-white/4 px-3 py-1">
                  每条消息扣 1 次
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
            支付已取消，没有扣费，也没有增加额度。
          </div>
        </section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.9fr)]">
        <section className="amo-panel amo-panel-interactive rounded-[1.8rem] p-6">
          <div className="text-xs uppercase tracking-[0.22em] text-white/38">Free Allowance</div>
          <h2 className="mt-3 text-2xl font-semibold text-white/92">免费体验额度</h2>
          <p className="mt-3 text-sm leading-6 text-white/64">
            首次进入 AMO 时，当前浏览器会自动获得免费对话额度，可直接用于角色对话。
          </p>
          <div className="mt-6 rounded-2xl border border-white/8 bg-white/4 p-4">
            <div className="text-3xl font-semibold text-white/92">{catalog?.free_allowance_credits ?? 100}</div>
            <div className="mt-1 text-xs uppercase tracking-[0.22em] text-white/34">Free Dialogue Credits</div>
          </div>
          <p className="mt-4 text-xs leading-6 text-white/44">
            不登录也可以使用免费额度；购买额度需要先登录账号，便于额度到账和后续找回。
          </p>
        </section>

        <section className="amo-panel amo-panel-interactive rounded-[1.8rem] p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.22em] text-white/38">Top-Up Pack</div>
              <h2 className="mt-3 text-2xl font-semibold text-white/92">{pack?.display_name || "1000 次加购包"}</h2>
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
              / {pack?.credits_per_unit ?? 1000} 次对话
            </div>
          </div>

          <p className="mt-4 text-sm leading-6 text-white/64">
            一次性购买，支付完成后立即补充到当前登录账号。不会自动续费，也不包含订阅。
          </p>

          <button
            type="button"
            onClick={startCheckout}
            disabled={creatingCheckout || !canStartCheckout}
            className="amo-button-primary mt-6 w-full rounded-2xl py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
          >
            {creatingCheckout
              ? "正在前往支付..."
              : authLoading
                ? "正在检查登录状态..."
                : !session.authenticated
                  ? "登录后购买"
                  : paymentsReady
                ? "购买对话额度"
                : "支付通道即将开放"}
          </button>

          <p className="mt-3 text-xs leading-5 text-white/42">
            购买即表示同意
            <Link href="/terms" className="text-emerald-200/80 hover:text-emerald-100">用户协议</Link>
            与
            <Link href="/privacy" className="text-emerald-200/80 hover:text-emerald-100">隐私协议</Link>
            。支付由 Creem 安全处理。
          </p>

          <div className="mt-4 flex flex-wrap gap-2 text-xs text-white/44">
            <span className="rounded-full border border-white/8 bg-white/4 px-3 py-1">
              一次性购买
            </span>
            <span className="rounded-full border border-white/8 bg-white/4 px-3 py-1">
              不自动续费
            </span>
          </div>
        </section>

        <section className="amo-panel rounded-[1.8rem] p-6">
          <div className="text-xs uppercase tracking-[0.22em] text-white/38">Usage</div>
          <h2 className="mt-3 text-2xl font-semibold text-white/92">额度说明</h2>
          <div className="mt-5 space-y-4 text-sm leading-6 text-white/64">
            <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
              每发送一条角色对话消息，消耗 1 次对话额度。
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
              免费额度可匿名使用；购买额度会绑定到登录账号，方便后续继续使用。
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/4 p-4">
              如遇支付或额度到账问题，请联系 {catalog?.support_email || "support@8xd.io"}。
            </div>
          </div>
        </section>
      </div>

      <section className="mt-8 grid gap-4 md:grid-cols-2">
        <div className="amo-panel rounded-[1.8rem] p-6">
          <div className="text-xs uppercase tracking-[0.22em] text-white/38">Included</div>
          <div className="mt-4 space-y-3 text-sm leading-6 text-white/64">
            <p>额度可用于 AMO 的角色对话。关系图谱、时间线、角色资料等浏览功能不消耗额度。</p>
            <p>生成失败时系统会尽量退回本次消耗，避免无效扣减。</p>
          </div>
        </div>

        <div className="amo-panel rounded-[1.8rem] p-6">
          <div className="text-xs uppercase tracking-[0.22em] text-white/38">Account</div>
          <div className="mt-4 space-y-3 text-sm leading-6 text-white/64">
            <p>
              不登录也可以直接使用 AMO 的免费额度。支付前需要登录，支付记录和购买额度会归到当前账号。
            </p>
            <p>
              想立即体验，可以直接前往 <Link href="/chat" className="text-emerald-200 hover:text-emerald-100">角色对话</Link>。
            </p>
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
