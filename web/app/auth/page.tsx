"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  createUserWithEmailAndPassword,
  getRedirectResult,
  sendEmailVerification,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  signOut,
  type ActionCodeSettings,
} from "firebase/auth";
import { apiFetch, type AuthSession } from "@/lib/api";
import { captureEvent } from "@/lib/analytics";
import { useAuthSession } from "@/components/AuthProvider";
import {
  createGoogleProvider,
  getIdentityPlatformAuth,
  getIdentityPlatformConfig,
} from "@/lib/identityPlatform";

type AuthMode = "login" | "register";

function sanitizeNextPath(value: string | null) {
  if (!value || !value.startsWith("/")) {
    return "/";
  }
  return value;
}

function resolveAuthErrorMessage(error: unknown) {
  const code = typeof error === "object" && error && "code" in error ? String(error.code) : "";
  switch (code) {
    case "auth/email-already-in-use":
      return "这个邮箱已经注册过了，可以直接登录。";
    case "auth/invalid-email":
      return "请输入有效的邮箱地址。";
    case "auth/weak-password":
      return "密码至少需要 6 位。";
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "邮箱或密码不正确。";
    case "auth/popup-closed-by-user":
      return "Google 登录窗口已关闭，请重试。";
    case "auth/popup-blocked":
      return "浏览器拦截了 Google 登录窗口，请重试或允许弹窗。";
    case "auth/too-many-requests":
      return "尝试次数过多，请稍后再试。";
    default:
      if (error instanceof Error && error.message) {
        return error.message;
      }
      return "认证失败，请稍后重试。";
  }
}

function buildEmailVerificationSettings(): ActionCodeSettings {
  return {
    url: `${window.location.origin}/auth?verified=1`,
    handleCodeInApp: false,
  };
}

function AuthPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { session, refreshSession, logout } = useAuthSession();
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resendingVerification, setResendingVerification] = useState(false);

  const nextPath = sanitizeNextPath(searchParams.get("next"));
  const verifiedMessage = searchParams.get("verified");

  const exchangeIdentityToken = useCallback(async (idToken: string) => {
    return apiFetch<AuthSession>("/auth/session", {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    });
  }, []);

  const finalizeIdentityPlatformLogin = useCallback(async () => {
    const auth = await getIdentityPlatformAuth();
    const user = auth.currentUser;
    if (!user) {
      throw new Error("登录态丢失，请重试。");
    }

    await user.reload();
    if (!user.emailVerified) {
      await signOut(auth);
      throw new Error("邮箱尚未验证，请先去邮件里完成验证。");
    }

    const idToken = await user.getIdToken();
    await exchangeIdentityToken(idToken);
    await signOut(auth);
    await refreshSession();
    router.replace(nextPath);
  }, [exchangeIdentityToken, nextPath, refreshSession, router]);

  useEffect(() => {
    let cancelled = false;

    const finishRedirectLogin = async () => {
      try {
        const auth = await getIdentityPlatformAuth();
        const result = await getRedirectResult(auth);
        if (!result || cancelled) {
          return;
        }

        setSubmitting(true);
        await finalizeIdentityPlatformLogin();
        captureEvent("auth_google_login_completed", {
          destination: nextPath,
          flow: "redirect",
        });
      } catch (error) {
        if (!cancelled) {
          setErrorMessage(resolveAuthErrorMessage(error));
          captureEvent("auth_google_login_failed", {
            destination: nextPath,
            flow: "redirect",
          });
        }
        try {
          const auth = await getIdentityPlatformAuth();
          await signOut(auth);
        } catch {
          // noop
        }
      } finally {
        if (!cancelled) {
          setSubmitting(false);
        }
      }
    };

    void finishRedirectLogin();

    return () => {
      cancelled = true;
    };
  }, [finalizeIdentityPlatformLogin, nextPath]);

  const handleGoogleLogin = async () => {
    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const config = await getIdentityPlatformConfig();
      if (!config.enabled) {
        throw new Error("Identity Platform 还没有配置完成。");
      }

      const auth = await getIdentityPlatformAuth();
      await signInWithPopup(auth, createGoogleProvider());
      await finalizeIdentityPlatformLogin();
      captureEvent("auth_google_login_completed", {
        destination: nextPath,
        flow: "popup",
      });
    } catch (error) {
      const code = typeof error === "object" && error && "code" in error ? String(error.code) : "";
      if (code === "auth/popup-blocked") {
        try {
          const auth = await getIdentityPlatformAuth();
          setSuccessMessage("正在跳转到 Google 登录...");
          captureEvent("auth_google_login_popup_blocked", {
            destination: nextPath,
          });
          await signInWithRedirect(auth, createGoogleProvider());
          return;
        } catch (redirectError) {
          setErrorMessage(resolveAuthErrorMessage(redirectError));
        }
      } else {
        setErrorMessage(resolveAuthErrorMessage(error));
      }
      captureEvent("auth_google_login_failed", {
        destination: nextPath,
        flow: code === "auth/popup-blocked" ? "redirect_fallback" : "popup",
      });
      try {
        const auth = await getIdentityPlatformAuth();
        await signOut(auth);
      } catch {
        // noop
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleRegister = async () => {
    if (password !== confirmPassword) {
      setErrorMessage("两次输入的密码不一致。");
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const auth = await getIdentityPlatformAuth();
      await createUserWithEmailAndPassword(auth, email.trim(), password);
      if (!auth.currentUser) {
        throw new Error("账号已创建，但无法获取当前用户。");
      }
      await sendEmailVerification(auth.currentUser, buildEmailVerificationSettings());
      await signOut(auth);
      setMode("login");
      setSuccessMessage("验证邮件已发送，请先去邮箱完成验证，再回来登录。");
      captureEvent("auth_email_registration_completed", {});
    } catch (error) {
      setErrorMessage(resolveAuthErrorMessage(error));
      try {
        const auth = await getIdentityPlatformAuth();
        await signOut(auth);
      } catch {
        // noop
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleEmailLogin = async () => {
    setSubmitting(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const auth = await getIdentityPlatformAuth();
      await signInWithEmailAndPassword(auth, email.trim(), password);
      await finalizeIdentityPlatformLogin();
      captureEvent("auth_email_login_completed", {
        destination: nextPath,
      });
    } catch (error) {
      setErrorMessage(resolveAuthErrorMessage(error));
      captureEvent("auth_email_login_failed", {
        destination: nextPath,
      });
      try {
        const auth = await getIdentityPlatformAuth();
        await signOut(auth);
      } catch {
        // noop
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleResendVerification = async () => {
    setResendingVerification(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const auth = await getIdentityPlatformAuth();
      await signInWithEmailAndPassword(auth, email.trim(), password);
      if (!auth.currentUser) {
        throw new Error("当前没有可用用户，无法重发验证邮件。");
      }
      await sendEmailVerification(auth.currentUser, buildEmailVerificationSettings());
      await signOut(auth);
      setSuccessMessage("验证邮件已重新发送，请检查收件箱和垃圾箱。");
      captureEvent("auth_verification_email_resent", {});
    } catch (error) {
      setErrorMessage(resolveAuthErrorMessage(error));
      try {
        const auth = await getIdentityPlatformAuth();
        await signOut(auth);
      } catch {
        // noop
      }
    } finally {
      setResendingVerification(false);
    }
  };

  return (
    <div className="relative mx-auto flex min-h-[calc(100vh-8rem)] max-w-xl items-center px-4 py-12">
      <div className="pointer-events-none absolute left-[-4rem] top-8 h-48 w-48 rounded-full bg-white/5 blur-3xl" />
      <div className="pointer-events-none absolute right-[-3rem] top-24 h-44 w-44 rounded-full bg-emerald-200/8 blur-3xl" />

      <div className="w-full">
        <div className="mb-7 text-center">
          <h1 className="amo-title-gradient text-4xl font-semibold tracking-[0.12em] md:text-5xl">
            AMO 账户
          </h1>
          <p className="mx-auto mt-4 max-w-md text-sm leading-6 text-white/58">
            使用 Google 或邮箱登录；也可以暂不登录继续体验 AMO。
          </p>
        </div>

        {session.authenticated && session.user ? (
          <section className="amo-panel rounded-[2rem] p-6 md:p-7">
            <div className="rounded-2xl border border-emerald-300/18 bg-emerald-300/10 px-4 py-4 text-center">
              <div className="text-xs uppercase tracking-[0.22em] text-emerald-100/70">Signed In</div>
              <div className="mt-3 text-lg font-medium text-white">
                {session.user.display_name || session.user.email}
              </div>
              <div className="mt-1 text-sm text-white/58">{session.user.email}</div>
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <Link
                href={nextPath}
                className="rounded-2xl bg-emerald-300/18 px-4 py-3 text-center text-sm font-medium text-white transition-colors hover:bg-emerald-300/24"
              >
                返回应用
              </Link>
              <button
                type="button"
                onClick={() => void logout()}
                className="rounded-2xl border border-white/10 px-4 py-3 text-sm text-white/70 transition-colors hover:border-white/16 hover:bg-white/4 hover:text-white"
              >
                退出登录
              </button>
            </div>
          </section>
        ) : (
          <section className="amo-panel rounded-[2rem] p-6 md:p-7">
            <div className="flex items-center gap-2 rounded-full border border-white/8 bg-white/4 p-1">
              <button
                type="button"
                onClick={() => setMode("login")}
                className={`flex-1 rounded-full px-4 py-2 text-sm transition-colors ${
                  mode === "login"
                    ? "bg-emerald-300/18 text-white"
                    : "text-white/56 hover:text-white/90"
                }`}
              >
                登录
              </button>
              <button
                type="button"
                onClick={() => setMode("register")}
                className={`flex-1 rounded-full px-4 py-2 text-sm transition-colors ${
                  mode === "register"
                    ? "bg-emerald-300/18 text-white"
                    : "text-white/56 hover:text-white/90"
                }`}
              >
                注册
              </button>
            </div>

            <div className="mt-6 flex flex-col gap-4">
              <button
                type="button"
                onClick={() => void handleGoogleLogin()}
                disabled={submitting}
                className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3 text-sm font-medium text-white transition-colors hover:border-white/16 hover:bg-white/8 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? "处理中..." : "使用 Google 登录"}
              </button>

              <div className="relative py-1 text-center text-xs uppercase tracking-[0.24em] text-white/34">
                <span className="bg-transparent px-2">或者</span>
              </div>

              <label className="flex flex-col gap-2 text-sm text-white/70">
                邮箱
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  className="amo-input rounded-2xl px-4 py-3 text-sm"
                  placeholder="you@example.com"
                />
              </label>

              <label className="flex flex-col gap-2 text-sm text-white/70">
                密码
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                  className="amo-input rounded-2xl px-4 py-3 text-sm"
                  placeholder="至少 6 位"
                />
              </label>

              {mode === "register" ? (
                <label className="flex flex-col gap-2 text-sm text-white/70">
                  确认密码
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    autoComplete="new-password"
                    className="amo-input rounded-2xl px-4 py-3 text-sm"
                    placeholder="再次输入密码"
                  />
                </label>
              ) : null}

              <button
                type="button"
                onClick={() => void (mode === "register" ? handleRegister() : handleEmailLogin())}
                disabled={submitting}
                className="rounded-2xl bg-emerald-300/18 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-emerald-300/24 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? "处理中..." : mode === "register" ? "注册并发送验证邮件" : "邮箱登录"}
              </button>

              {mode === "login" ? (
                <button
                  type="button"
                  onClick={() => void handleResendVerification()}
                  disabled={resendingVerification || !email || !password}
                  className="rounded-2xl border border-white/10 px-4 py-3 text-sm text-white/70 transition-colors hover:border-white/16 hover:bg-white/4 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {resendingVerification ? "发送中..." : "重发验证邮件"}
                </button>
              ) : null}

              {errorMessage ? (
                <div className="rounded-2xl border border-rose-300/18 bg-rose-300/10 px-4 py-3 text-sm text-rose-100">
                  {errorMessage}
                </div>
              ) : null}

              {successMessage ? (
                <div className="rounded-2xl border border-emerald-300/18 bg-emerald-300/10 px-4 py-3 text-sm text-emerald-50">
                  {successMessage}
                </div>
              ) : null}

              {verifiedMessage ? (
                <div className="rounded-2xl border border-emerald-300/18 bg-emerald-300/10 px-4 py-3 text-sm text-emerald-50">
                  邮箱验证流程已返回 AMO。现在可以直接用邮箱密码登录。
                </div>
              ) : null}

              <div className="pt-1 text-center">
                <Link href={nextPath} className="text-sm text-white/48 transition-colors hover:text-white/80">
                  暂不登录，继续使用 AMO
                </Link>
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

export default function AuthPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-3xl px-4 py-16 text-center text-sm text-white/58">加载登录页...</div>}>
      <AuthPageInner />
    </Suspense>
  );
}
