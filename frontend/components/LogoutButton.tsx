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
      className="account-cancel logout-button"
    >
      Logout
    </button>
  );
}