"use client";



import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { useRouter } from "next/navigation";



import ChatWindow from "@/components/ChatWindow";

import DailyLimitModal from "@/components/DailyLimitModal";

import GuestSignupModal from "@/components/GuestSignupModal";
import {claimTrial, initTrial, guestSessions, guestMessages, guestSend, guestStatus, type Allowance} from "@/lib/trial";
import Sidebar from "@/components/Sidebar";



import { createClient } from "@/lib/supabase/client";



import {

  ApiError,

  getSession,

  getSessions,

  sendMessage,

} from "@/lib/api";



import type {

  Conversation,

  Message,

} from "@/types/chat";





function subscribeMobile(callback: () => void) {

  const query = window.matchMedia("(max-width: 767px)");

  query.addEventListener("change", callback);

  return () => query.removeEventListener("change", callback);

}



function getMobileSnapshot() {

  return window.matchMedia("(max-width: 767px)").matches;

}



export default function Home() {

  const router = useRouter();
  const [guest,setGuest]=useState(false);
  const [allowance,setAllowance]=useState<Allowance|null>(null);
  const [signup,setSignup]=useState(false);
  const [initError,setInitError]=useState("");
  const [attempt,retryInit]=useState(0);
  const blocked=guest && (!allowance || allowance.signup_required);

  const mobile = useSyncExternalStore(subscribeMobile, getMobileSnapshot, () => false);

  const [navigationOpen, setNavigationOpen] = useState(false);

  const closeNavigation = useCallback(() => setNavigationOpen(false), []);



  useEffect(() => {

    const query = window.matchMedia("(max-width: 767px)");

    query.addEventListener("change", closeNavigation);

    return () => query.removeEventListener("change", closeNavigation);

  }, [closeNavigation]);



  const [messages, setMessages] =

    useState<Message[]>([]);



  const [sessionId, setSessionId] =

    useState<string | null>(null);



  const [

    conversations,

    setConversations,

  ] = useState<Conversation[]>([]);



  const [loading, setLoading] =

    useState(false);



  const [

    dailyLimitReached,

    setDailyLimitReached,

  ] = useState(false);



  const [

    showLimitModal,

    setShowLimitModal,

  ] = useState(false);



  const [

    userEmail,

    setUserEmail,

  ] = useState("");



  const [

    checkingAuth,

    setCheckingAuth,

  ] = useState(true);





  useEffect(() => {

    async function initializePage() {

      const supabase = createClient();



      const {

        data: { user },

        error,

      } = await supabase.auth.getUser();



      if (!user) {
        if (error && error.name !== "AuthSessionMissingError") {
          setInitError("Unable to verify your account. Please retry."); return;
        }
        setGuest(true);
        try {
          const status=await initTrial();
          const {sessions}=await guestSessions();
          const latest=sessions[0]?.id;
          if(latest) {
            const saved=await guestMessages(latest);
            setSessionId(latest); setMessages(saved.messages);
          }
          setConversations(sessions.map(s=>({sessionId:s.id,title:s.title})));
          setAllowance(status); setSignup(status.signup_required); setCheckingAuth(false);
        } catch(e) {setInitError(e instanceof Error?e.message:"Unable to open trial.");}
        return;
      }
      setGuest(false);
      let claimedSession:string|undefined;
      try {
        const result=await claimTrial();
        claimedSession=result.session_id;
      } catch {
        setInitError("Your account is signed in, but guest history could not be transferred. Retry to recover it.");
      }
      setUserEmail(

        user.email ?? ""

      );





      try {

        const response =

          await getSessions();



        const loadedConversations:

          Conversation[] =

          response.sessions.map(

            (session) => ({

              sessionId: session.id,

              title: session.title,

            })

          );



        if(claimedSession) {
          const saved=await getSession(claimedSession);
          setSessionId(claimedSession); setMessages(saved.messages);
        }
        setConversations(

          loadedConversations

        );

      } catch (error) {

        console.error(

          "Failed to load sessions:",

          error

        );

      }



      setCheckingAuth(false);

    }





    initializePage();

  }, [router,attempt]);





  async function refreshSessions() {

    try {

      const response =

        await (guest ? guestSessions() : getSessions());



      const loadedConversations:

        Conversation[] =

        response.sessions.map(

          (session) => ({

            sessionId: session.id,

            title: session.title,

          })

        );



      setConversations(

        loadedConversations

      );

    } catch (error) {

      console.error(

        "Failed to refresh sessions:",

        error

      );

    }

  }





  function handleNewChat() {

    if (blocked) { setSignup(Boolean(allowance?.signup_required)); return; }
    if (dailyLimitReached) {

      setShowLimitModal(true);

      return;

    }



    setSessionId(null);

    setMessages([]);

  }





  async function handleSendMessage(

    message: string

  ) {

    if (checkingAuth || blocked) {setSignup(Boolean(allowance?.signup_required));return;}
    if (

      loading

      || dailyLimitReached

    ) {

      if (dailyLimitReached) {

        setShowLimitModal(true);

      }



      return;

    }





    const userMessage: Message = {

      role: "user",

      content: message,

    };





    setMessages((current) => [

      ...current,

      userMessage,

    ]);



    setLoading(true);





    try {

      const response = guest ? await guestSend(message,sessionId) : await sendMessage(message,sessionId);
      if ("guest" in response) {
        const status=response.guest as Allowance;
        setAllowance(status); setSignup(status.signup_required);
      }
      const assistantMessage:

        Message = {

          role: "assistant",

          content: response.answer,

        };





      setMessages((current) => [

        ...current,

        assistantMessage,

      ]);





      if (sessionId === null) {

        setSessionId(

          response.session_id

        );



        await refreshSessions();

      }

    } catch (error) {
      if(guest) {
        // Synchronize a final response after lost delivery or another tab's send.
        try {
          const status=await guestStatus(); setAllowance(status); setSignup(status.signup_required);
          if(status.signup_required) {
            const {sessions}=await guestSessions(); const latest=sessionId || sessions[0]?.id;
            if(latest) { const saved=await guestMessages(latest); setMessages(saved.messages); setSessionId(latest); }
            return;
          }
        } catch { /* Preserve the original request error. */ }
      }

      if (

        error instanceof ApiError

        && error.code ===

          "DAILY_LIMIT_REACHED"

      ) {

        setDailyLimitReached(true);

        setShowLimitModal(true);



        setMessages((current) =>

          current.slice(0, -1)

        );



        return;

      }





      const errorMessage =

        error instanceof Error

          ? error.message

          : "Something went wrong.";





      setMessages((current) => [

        ...current,

        {

          role: "assistant",

          content:

            `Error: ${errorMessage}`,

        },

      ]);

    } finally {

      setLoading(false);

    }

  }





  async function handleSelectConversation(

    selectedSessionId: string

  ) {

    if (loading) {

      return;

    }



    setLoading(true);





    try {

      const response =

        await (guest ? guestMessages : getSession)(

          selectedSessionId

        );





      setSessionId(

        selectedSessionId

      );





      setMessages(

        response.messages.map(

          (message) => ({

            id: message.id,

            role: message.role,

            content: message.content,

          })

        )

      );

    } catch (error) {

      console.error(

        "Failed to load conversation:",

        error

      );

    } finally {

      setLoading(false);

    }

  }





  return (

    <div className="workspace">

      <Sidebar

        conversations={conversations}

        activeSessionId={sessionId}

        onSelectConversation={

          (id) => { closeNavigation(); void handleSelectConversation(id); }

        }

        onNewChat={() => { closeNavigation(); handleNewChat(); }}

        mobile={mobile}

        open={navigationOpen}

        onClose={closeNavigation}

        disabled={dailyLimitReached || loading}

        userEmail={userEmail}
        guest={guest || checkingAuth}

        accountDisabled={loading}

        onAccountDeleted={() => {

          setMessages([]);

          setSessionId(null);

          setConversations([]);

          setUserEmail("");

          setCheckingAuth(true);

          router.replace("/login");

          router.refresh();

        }}

      />



      <div className="chat-canvas" inert={mobile && navigationOpen}>

      {initError && <div role="alert" className="account-surface">{initError} <button onClick={()=>{setInitError("");retryInit(n=>n+1);}}>Retry</button> · <a href="/login">Log in</a></div>}
      <ChatWindow

        messages={messages}

        loading={loading}

        disabled={dailyLimitReached || blocked || checkingAuth}
        guestLabel={checkingAuth ? "Opening WaveGuide…" : guest && allowance ? `${allowance.messages_remaining} free message${allowance.messages_remaining===1?"":"s"} remaining` : undefined}

        onOpenNavigation={() => setNavigationOpen(true)}

        navigationOpen={mobile && navigationOpen}
        mobile={mobile}

        onSendMessage={

          handleSendMessage

        }

      />



      </div>



      <GuestSignupModal open={signup} onClose={()=>setSignup(false)} />
      <DailyLimitModal

        open={showLimitModal}

        onClose={() =>

          setShowLimitModal(false)

        }

      />

    </div>

  );

}