import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy | WaveGuide",
  description: "How WaveGuide handles your coaching conversations, Riot gameplay data, guest trial, and account.",
};

export default function PrivacyPage() {
  return (
    <main className="privacy-page">
      <article className="privacy-card glass">
        <Link className="privacy-link" href="/">&larr; Back to chat</Link>
        <h1>Privacy Policy</h1>
        <p>Last updated <time dateTime="2026-11-16">November 16, 2026</time></p>
        <p>WaveGuide is an independent League of Legends coaching assistant. This policy explains what happens to your information when you ask for coaching, try the service as a guest, or create an account.</p>

        <h2>Your account and conversations</h2>
        <p>Supabase handles your email address, password sign-in, verification and authentication session. WaveGuide uses your account ID to save chat titles, messages, responses, timestamps and associated coaching context in Supabase. It also records usage to enforce daily account limits.</p>

        <h2>When you ask about a game</h2>
        <p>WaveGuide sends player or match identifiers to the Riot Games API to find the games you request. It retrieves match IDs, participants, statistics and timeline events to analyze play. When you link a Riot account, WaveGuide saves your game name, tag, routing region and Riot player identifier (PUUID) with your account.</p>
        <p>WaveGuide retrieves match records for analysis as needed. Selected gameplay evidence, match identifiers and conclusions can remain in saved messages and their coaching context.</p>

        <h2>AI coaching</h2>
        <p>WaveGuide sends your question and relevant conversation context to Google Gemini to understand requests and generate answers. For a match review, the prompt can also contain selected gameplay evidence such as champions, statistics, item choices and timed events. Personal information you type into a chat may therefore reach Google. Avoid including passwords or other sensitive details.</p>

        <h2>Cookies and the guest trial</h2>
        <p>An essential cookie identifies your five-message guest trial across refreshes. The browser holds a random token and the database stores its digest. WaveGuide stores guest conversations, successful response counts and request records so it can enforce limits and handle retries. Session storage holds a pending request ID and digest to help recover an interrupted submission. Supabase session cookies maintain account sign-in.</p>
        <p>Vercel serves the frontend and forwards guest requests. The backend derives a keyed identifier from the source IP address for abuse prevention. Trial rate-limit records use that identifier. Hosting services also process connection information to deliver requests. Operational logs can include errors and match identifiers used to troubleshoot analysis.</p>

        <h2>How long information stays</h2>
        <p>Guest sessions expire after 90 days. Scheduled database cleanup removes expired sessions and their unclaimed chats and retry records. Reaching five messages does not erase your conversation. Signing in with a verified account in the original browser can move guest history into your account and remove the guest copies. A claim record tied to your account prevents duplicate transfers.</p>
        <p>Guest rate-limit windows are eligible for cleanup one day after they expire. Account chats have no automatic expiry in the application. Hosting logs and backups may have separate retention periods.</p>

        <h2>Security and international processing</h2>
        <p>WaveGuide uses HTTPS in deployment, restricts access to account conversations and keeps guest database operations behind its backend. The production guest cookie is marked Secure and HttpOnly. Riot Games, Google, Supabase and Vercel may process information in countries other than the one where you live.</p>

        <h2>Your choices</h2>
        <p>Open Chat History to read your saved conversations. Your account menu shows your email address. Choose Delete Account there and confirm to remove your account and its associated chats and linked account records. Clearing your guest cookie will remove your browser&apos;s access to an unclaimed conversation. The stored conversation still follows the guest expiry schedule.</p>

        <h2>Children and privacy</h2>
        <p>If you are a parent or guardian and believe a child has shared personal information with WaveGuide, contact us so we can review the information and help with removal.</p>

        <h2>Changes and contact</h2>
        <p>We will update the date above when we revise this policy. For questions about your information or help with access or deletion, email <a className="privacy-link" href="mailto:cyltar2@gmail.com">cyltar2@gmail.com</a>.</p>
      </article>
    </main>
  );
}
