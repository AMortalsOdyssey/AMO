import { SITE_DOMAIN, SUPPORT_EMAIL, SUPPORT_EMAIL_HREF } from "@/lib/site";

export default function ContactPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <section className="amo-panel rounded-[2rem] p-6 md:p-8">
        <div className="mb-6">
          <div className="mb-3 inline-flex rounded-full border border-white/8 bg-white/4 px-3 py-1 text-[11px] uppercase tracking-[0.26em] text-white/46">
            Contact
          </div>
          <h1 className="text-3xl font-semibold tracking-[0.08em] text-white/92">联系方式</h1>
          <p className="mt-3 text-sm leading-6 text-white/54">
            如需处理账户、支付、额度到账、退款或隐私相关问题，请通过支持邮箱联系 AMO。
          </p>
        </div>

        <div className="space-y-5 text-sm leading-7 text-white/70">
          <section className="rounded-2xl border border-white/8 bg-white/4 p-5">
            <div className="text-xs uppercase tracking-[0.22em] text-white/38">Support Email</div>
            <a
              href={SUPPORT_EMAIL_HREF}
              className="mt-3 inline-flex text-lg font-medium text-emerald-100 transition-colors hover:text-white"
            >
              {SUPPORT_EMAIL}
            </a>
            <p className="mt-3 text-white/56">
              请在邮件中说明你的登录邮箱、订单信息或问题截图，便于我们核查。
            </p>
          </section>

          <section className="grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl border border-white/8 bg-white/4 p-5">
              <div className="text-xs uppercase tracking-[0.22em] text-white/38">Website</div>
              <p className="mt-3 text-white/64">{SITE_DOMAIN}</p>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/4 p-5">
              <div className="text-xs uppercase tracking-[0.22em] text-white/38">Billing</div>
              <p className="mt-3 text-white/64">支付由 Creem 安全处理，AMO 负责额度到账与服务支持。</p>
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
