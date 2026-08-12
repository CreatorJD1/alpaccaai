export type HouseBackendStatus = "offline" | "connecting" | "live" | "token";

export type HouseReadTool = {
  id: string;
  label: string;
  endpoint: string;
  method: "GET";
};

export const HOUSE_READ_TOOLS: readonly HouseReadTool[] = Object.freeze([
  { id: "self", label: "Self state", endpoint: "/introspect", method: "GET" },
  { id: "memory", label: "Room memory search", endpoint: "/memories/search", method: "GET" },
  { id: "journal", label: "Journal", endpoint: "/journal", method: "GET" },
  { id: "studio", label: "Growth queue", endpoint: "/growth", method: "GET" },
  { id: "home", label: "Internal home state", endpoint: "/home/state", method: "GET" },
]);

export function houseReadTool(id: string) {
  return HOUSE_READ_TOOLS.find((tool) => tool.id === id);
}

export function houseReadToolControl(id: string, status: HouseBackendStatus) {
  const tool = houseReadTool(id);
  if (!tool) {
    return { disabled: true, title: "This control has no registered backend endpoint." };
  }
  if (status !== "live") {
    return {
      disabled: true,
      title: `${tool.label} is unavailable until the live Alpecca backend reconnects.`,
    };
  }
  return { disabled: false, title: `${tool.method} ${tool.endpoint}` };
}

export type ToolLibrarySnapshot = {
  currentRoom: string;
  parlorKnown: boolean;
  parlorCurrent: boolean;
  actuatorEnabled: boolean;
  executableTools: string[];
  googleWorkspaceReady: boolean;
  googleWorkspaceState: string;
  googleWorkspaceCapabilities: string[];
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function buildToolLibrarySnapshot(data: Record<string, unknown>): ToolLibrarySnapshot {
  const growth = record(data.growth);
  const home = record(data.home);
  const runtime = record(data.runtime);
  const senses = record(runtime.senses);
  const integrations = record(runtime.integrations);
  const googleWorkspace = record(integrations.google_workspace);
  const rooms = Array.isArray(home.rooms) ? home.rooms.map(record) : [];
  const currentRoom = String(home.location || home.current_room || home.room || "unknown").trim() || "unknown";
  const executableTools = Array.isArray(growth.executable_tools)
    ? growth.executable_tools
        .filter((value): value is string => typeof value === "string" && Boolean(value.trim()))
        .map((value) => value.trim())
        .sort()
    : [];
  return {
    currentRoom,
    parlorKnown: rooms.some((room) => String(room.id || "").toLowerCase() === "parlor"),
    parlorCurrent: currentRoom.toLowerCase() === "parlor",
    actuatorEnabled: senses.actions === true,
    executableTools,
    googleWorkspaceReady: googleWorkspace.ready === true,
    googleWorkspaceState: String(googleWorkspace.state || "unavailable"),
    googleWorkspaceCapabilities: Array.isArray(googleWorkspace.capabilities)
      ? googleWorkspace.capabilities.filter((value): value is string => typeof value === "string")
      : [],
  };
}
