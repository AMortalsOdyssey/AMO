export default function PrivacyPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <section className="amo-panel rounded-[2rem] p-6 md:p-8">
        <div className="mb-6">
          <div className="mb-3 inline-flex rounded-full border border-white/8 bg-white/4 px-3 py-1 text-[11px] uppercase tracking-[0.26em] text-white/46">
            Privacy Policy
          </div>
          <h1 className="text-3xl font-semibold tracking-[0.08em] text-white/92">隐私协议</h1>
          <p className="mt-3 text-sm leading-6 text-white/54">
            本页面用于说明 `amo.8xd.io` 在提供角色对话、图谱浏览、剧情演绎等服务时，对用户信息的处理方式。
          </p>
        </div>

        <div className="space-y-6 text-sm leading-7 text-white/70">
          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">1. 收集范围</h2>
            <p>
              我们可能收集你在使用本站过程中主动提交的对话内容、操作记录、设备基础信息，以及为保障服务稳定性所需的访问日志。
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">2. 使用目的</h2>
            <p>
              收集的信息主要用于维持站点运行、排查故障、优化交互体验、改进模型效果，以及处理你主动提交的反馈问题。
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">3. 信息共享</h2>
            <p>
              除法律法规要求、保护平台安全或完成基础云服务调用外，我们不会无故向无关第三方出售你的个人信息。若调用第三方模型或云基础设施，会在实现服务所必需的范围内传递相关请求数据。
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">4. 存储与安全</h2>
            <p>
              我们会采取合理的技术和管理措施保护数据安全，但互联网传输并非绝对安全。请避免在站内输入与你个人账户、支付或其他高敏感场景相关的机密信息。
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">5. 联系方式</h2>
            <p>
              若你对隐私处理方式有疑问，可通过站内反馈入口联系我们；相关说明更新后，将以本页最新内容为准。
            </p>
          </section>
        </div>
      </section>
    </div>
  );
}
