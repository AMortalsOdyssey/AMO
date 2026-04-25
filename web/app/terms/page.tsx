export default function TermsPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-10 md:py-14">
      <section className="amo-panel rounded-[2rem] p-6 md:p-8">
        <div className="mb-6">
          <div className="mb-3 inline-flex rounded-full border border-white/8 bg-white/4 px-3 py-1 text-[11px] uppercase tracking-[0.26em] text-white/46">
            Terms of Use
          </div>
          <h1 className="text-3xl font-semibold tracking-[0.08em] text-white/92">用户协议</h1>
          <p className="mt-3 text-sm leading-6 text-white/54">
            本协议适用于你访问和使用 `amo.8xd.io` 提供的资料索引、角色对话、交互演绎、图谱浏览及相关功能。
          </p>
        </div>

        <div className="space-y-6 text-sm leading-7 text-white/70">
          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">1. 服务说明</h2>
            <p>
              本站提供基于公开资料整理、结构化建模与交互演绎的实验性服务。我们会持续调整功能、模型、内容展示与服务结构，必要时可暂停、变更或下线部分功能。
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">2. 使用规范</h2>
            <p>
              你不得利用本站从事违法违规活动，不得干扰服务稳定性，不得尝试绕过访问限制、批量抓取、恶意压测、注入攻击，或上传、传播违法与侵权内容。
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">3. 内容与免责</h2>
            <p>
              站内部分内容来自公开资料整理、结构化建模、模型生成或自动推断，可能存在误差、缺漏或与既有资料不完全一致的情况。你应自行判断相关内容的准确性，本站不对因使用这些内容造成的直接或间接损失承担责任。
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">4. 知识产权</h2>
            <p>
              站点程序、页面设计、整理后的结构化数据与交互体验归 `amo.8xd.io` 运营方所有。未经书面许可，不得擅自复制、分发、镜像、商用或用于训练其他公开服务。
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">5. 支付、额度与退款</h2>
            <p>
              AMO 提供的一次性购买项目为角色对话额度，不属于订阅服务，不会自动续费。购买前需要登录账号，支付完成后额度会补充到当前登录账号，可用于站内角色对话功能。每发送一条角色对话消息通常消耗 1 次额度；如生成失败，系统会尽量退回本次消耗。
            </p>
            <p className="mt-3">
              支付流程由第三方支付服务商 Creem 安全处理，AMO 不直接保存你的银行卡或完整支付凭证。支付成功后如额度未及时到账，请通过站内反馈入口或支持邮箱联系我们，并提供订单相关信息以便核查。退款、拒付或支付争议将结合 Creem 的交易记录、支付服务商规则以及 AMO 的实际服务交付情况处理。
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-lg font-medium text-white/88">6. 协议更新</h2>
            <p>
              我们可根据服务调整随时更新本协议。更新后的版本自发布之日起生效；你继续使用本站，视为接受更新后的条款。
            </p>
          </section>
        </div>
      </section>
    </div>
  );
}
