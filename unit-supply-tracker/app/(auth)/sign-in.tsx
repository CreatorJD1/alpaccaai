// Sign-in screen. INVITE-ONLY: there is no "create account" button. Accounts are
// minted by the supply clerk/sergeant in Supabase and the user just signs in here.
// If a signed-in user has no profile (not invited / not yet attached to a unit),
// the gate keeps them out and we show the "ask your supply clerk" notice.

import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { supabase } from "../../lib/supabase";
import { useSession } from "../../lib/session";
import { colors, space } from "../../lib/theme";

export default function SignIn() {
  const { session, profile } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Signed in but no profile = authenticated yet not invited to a unit.
  const signedInButNotInvited = !!session && !profile;

  async function signIn() {
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
    if (error) setError(error.message);
    setBusy(false);
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1, justifyContent: "center", padding: space.xl }}
      >
        <Text style={{ color: colors.ink, fontSize: 26, fontWeight: "800" }}>
          Supply Tracker
        </Text>
        <Text style={{ color: colors.dim, marginBottom: space.xl }}>
          C Battery · 2-218th FA — private, invite-only
        </Text>

        {signedInButNotInvited ? (
          <View
            style={{
              backgroundColor: colors.panel,
              borderColor: colors.warn,
              borderWidth: 1,
              borderRadius: 10,
              padding: space.lg,
            }}
          >
            <Text style={{ color: colors.ink, fontWeight: "700", marginBottom: space.sm }}>
              Account not yet authorized
            </Text>
            <Text style={{ color: colors.dim }}>
              You're signed in, but your account hasn't been added to a unit. Ask
              your supply clerk or supply sergeant to invite you.
            </Text>
            <Pressable onPress={() => supabase.auth.signOut()} style={{ marginTop: space.lg }}>
              <Text style={{ color: colors.accent, fontWeight: "700" }}>Sign out</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <TextInput
              placeholder="Email"
              placeholderTextColor={colors.dim}
              autoCapitalize="none"
              keyboardType="email-address"
              value={email}
              onChangeText={setEmail}
              style={inputStyle}
            />
            <TextInput
              placeholder="Password"
              placeholderTextColor={colors.dim}
              secureTextEntry
              value={password}
              onChangeText={setPassword}
              style={inputStyle}
            />
            {error && <Text style={{ color: colors.bad, marginBottom: space.md }}>{error}</Text>}
            <Pressable
              onPress={signIn}
              disabled={busy}
              style={{
                backgroundColor: colors.accent,
                borderRadius: 10,
                padding: space.lg,
                alignItems: "center",
              }}
            >
              {busy ? (
                <ActivityIndicator color={colors.accentInk} />
              ) : (
                <Text style={{ color: colors.accentInk, fontWeight: "800" }}>Sign in</Text>
              )}
            </Pressable>
            <Text style={{ color: colors.dim, fontSize: 12, marginTop: space.lg, textAlign: "center" }}>
              No public sign-up. Accounts are created by your supply section.
            </Text>
          </>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const inputStyle = {
  backgroundColor: colors.panel,
  borderColor: colors.border,
  borderWidth: 1,
  borderRadius: 10,
  color: colors.ink,
  padding: space.lg,
  marginBottom: space.md,
} as const;
