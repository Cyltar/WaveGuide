"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import Icon from "@/components/Icon";
import LoadingScreen from "@/components/LoadingScreen";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const supabase = createClient();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [errorMessage, setErrorMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setErrorMessage("");
    setLoading(true);

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      setLoading(false);
      if (error.message.toLowerCase().includes("email not confirmed")) {
        setErrorMessage("Please verify your email before signing in.");
      }
      else {
        setErrorMessage(error.message);
      }
      return;
    }

    router.push("/");
    router.refresh();
  }

  if (loading) return <LoadingScreen />;

  return (
    <main className="auth-page">
      <div className="auth-card glass">
        <div className="brand auth-brand"><Icon name="wave" className="brand-mark" />WaveGuide</div>
        <h1 className="auth-title">
          Welcome back
        </h1>

        <p className="mt-2 text-sm text-gray-400">
          Sign in to continue to WaveGuide.
        </p>

        <form
          onSubmit={handleLogin}
          className="mt-8 flex flex-col gap-4"
        >
          <div>
            <label htmlFor="email" className="mb-2 block text-sm text-gray-300">
              Email
            </label>

            <input
              id="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              autoComplete="email"
              className="w-full rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-blue-500"
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-2 block text-sm text-gray-300">
              Password
            </label>

            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              autoComplete="current-password"
              className="w-full rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-blue-500"
              placeholder="Your password"
            />
          </div>

          {errorMessage && (
            <div role="alert" className="account-warning">
              {errorMessage}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="primary-button"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-gray-400">
          Don&apos;t have an account?{" "}
          <Link
            href="/signup"
            className="text-blue-400 hover:text-blue-300"
          >
            Create one
          </Link>
        </p>

        <p className="mt-6 text-center text-xs leading-5 text-gray-500">
          WaveGuide is an independent fan project and is not endorsed by
          or affiliated with Riot Games. Riot Games and related properties
          are trademarks of Riot Games, Inc.
        </p>
        <p className="auth-privacy"><Link className="privacy-link" href="/privacy">Privacy Policy</Link></p>
      </div>
    </main>
  );
}