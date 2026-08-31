import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import LogoutButton from "@/components/LogoutButton";

export default async function AuthTestPage() {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return (
      <main className="min-h-screen bg-gradient-to-br from-[#02050b] via-[#050c1d] to-[#071426] flex items-center justify-center px-4">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-8 text-white">
          <h1 className="text-2xl font-bold">
            Not signed in
          </h1>

          <Link
            href="/login"
            className="mt-4 inline-block text-blue-400"
          >
            Go to login
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-[#02050b] via-[#050c1d] to-[#071426] flex items-center justify-center px-4">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-white/5 p-8 text-white">
        <h1 className="text-2xl font-bold">
          Authentication works
        </h1>

        <div className="mt-6 space-y-3 text-sm text-gray-300">
          <p>
            <strong>Email:</strong> {user.email}
          </p>

          <p>
            <strong>User ID:</strong> {user.id}
          </p>

          <p>
            <strong>Email confirmed:</strong>{" "}
            {user.email_confirmed_at ? "Yes" : "No"}
          </p>
        </div>

        <div className="mt-6">
          <LogoutButton />
        </div>
      </div>
    </main>
  );
}