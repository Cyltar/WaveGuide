"use client";



import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { useRouter } from "next/navigation";



import ChatWindow from "@/components/ChatWindow";

import DailyLimitModal from "@/components/DailyLimitModal";

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



      if (error || user === null) {

        console.error(

          "Failed to get user:",

          error?.message

        );



        router.replace("/login");

        return;

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

  }, [router]);





  async function refreshSessions() {

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

      const response =

        await sendMessage(

          message,

          sessionId

        );





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

        await getSession(

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





  if (checkingAuth) {

    return (

      <main className="auth-page" aria-label="Loading WaveGuide"><p role="status">Opening WaveGuide…</p></main>

    );

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

      <ChatWindow

        messages={messages}

        loading={loading}

        disabled={dailyLimitReached}

        onOpenNavigation={() => setNavigationOpen(true)}

        navigationOpen={mobile && navigationOpen}
        mobile={mobile}

        onSendMessage={

          handleSendMessage

        }

      />



      </div>



      <DailyLimitModal

        open={showLimitModal}

        onClose={() =>

          setShowLimitModal(false)

        }

      />

    </div>

  );

}