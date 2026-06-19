// Root layout: wraps the whole app in the SessionProvider and routes between the
// auth gate and the main tabs based on whether the user is signed in AND invited
// (has a profile). No profile => stays on the sign-in / "not invited" screen.

import { Stack, useRouter, useSegments } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { SessionProvider, useSession } from "../lib/session";
import { colors } from "../lib/theme";

function Gate() {
  const { loading, session, profile } = useSession();
  const segments = useSegments();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    const inAuth = segments[0] === "(auth)";
    const allowed = !!session && !!profile; // signed in AND invited
    if (!allowed && !inAuth) {
      router.replace("/(auth)/sign-in");
    } else if (allowed && inAuth) {
      router.replace("/(tabs)");
    }
  }, [loading, session, profile, segments]);

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg, justifyContent: "center" }}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="(auth)" />
      <Stack.Screen name="(tabs)" />
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <SessionProvider>
        <Gate />
      </SessionProvider>
    </SafeAreaProvider>
  );
}
