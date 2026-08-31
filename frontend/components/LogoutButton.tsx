"use client";

import { useRouter } from "next/navigation";

import { createClient } from "@/lib/supabase/client";


export default function LogoutButton() {
  const router = useRouter();


  async function handleLogout() {
    const supabase = createClient();

    const { error } =
      await supabase.auth.signOut();

    if (error) {
      console.error(
        "Logout failed:",
        error.message
      );

      return;
    }

    router.push("/login");
    router.refresh();
  }


  return (
    <button
      onClick={handleLogout}
      className="rounded-lg border border-white/10 px-4 py-2 text-sm text-gray-300 transition hover:bg-white/5 hover:text-white"
    >
      Logout
    </button>
  );
}