export type VaultConflictPolicy = "keep" | "copy" | "overwrite";

export interface VaultDocument {
  filename: string;
  markdown: string;
}

export type VaultWriteResult =
  | { status: "written" | "kept"; filename: string }
  | { status: "downloaded"; filename: string; reason: string };

type FileSystemHandleKind = "file" | "directory";

interface FileSystemHandle {
  kind: FileSystemHandleKind;
  name: string;
  queryPermission?: (options: { mode: "read" | "readwrite" }) => Promise<PermissionState>;
  requestPermission?: (options: { mode: "read" | "readwrite" }) => Promise<PermissionState>;
}

interface FileSystemFileHandle extends FileSystemHandle {
  kind: "file";
  getFile: () => Promise<File>;
  createWritable: () => Promise<{
    write: (data: string) => Promise<void>;
    close: () => Promise<void>;
    abort?: () => Promise<void>;
  }>;
}

interface FileSystemDirectoryHandle extends FileSystemHandle {
  kind: "directory";
  getFileHandle: (name: string, options?: { create?: boolean }) => Promise<FileSystemFileHandle>;
}

type DirectoryPicker = (options?: {
  id?: string;
  mode?: "read" | "readwrite";
  startIn?: "documents" | "downloads";
}) => Promise<FileSystemDirectoryHandle>;

declare global {
  interface Window {
    showDirectoryPicker?: DirectoryPicker;
  }
}

export function safeVaultFilename(title: string, stableId?: string): string {
  const base = Array.from(title.normalize("NFKC"), (character) => character.charCodeAt(0) < 32 ? " " : character)
    .join("")
    .replace(/[<>:"/\\|?*]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\.+|\.+$/g, "")
    .slice(0, 90)
    .trim();
  const identity = stableId?.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 24);
  const name = base || (identity ? `lifeos-${identity}` : "lifeos-note");
  return name.toLowerCase().endsWith(".md") ? name : `${name}.md`;
}

export function withObsidianFrontmatter(
  markdown: string,
  fields: Record<string, string | number | string[]>,
): string {
  const body = markdown.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
  const lines = ["---"];
  for (const [key, value] of Object.entries(fields)) {
    if (!/^[a-zA-Z_][a-zA-Z0-9_-]*$/.test(key)) continue;
    if (Array.isArray(value)) {
      if (!value.length) {
        lines.push(`${key}: []`);
        continue;
      }
      lines.push(`${key}:`);
      for (const entry of value) lines.push(`  - ${JSON.stringify(entry)}`);
    } else if (typeof value === "number") {
      lines.push(`${key}: ${value}`);
    } else {
      lines.push(`${key}: ${JSON.stringify(value)}`);
    }
  }
  lines.push("---", "", body.trimStart());
  return lines.join("\n");
}

async function findFile(
  directory: FileSystemDirectoryHandle,
  name: string,
): Promise<FileSystemFileHandle | null> {
  try {
    return await directory.getFileHandle(name);
  } catch (error) {
    if (error instanceof DOMException && error.name === "NotFoundError") return null;
    throw error;
  }
}

async function writeFile(handle: FileSystemFileHandle, markdown: string): Promise<void> {
  const writable = await handle.createWritable();
  try {
    await writable.write(markdown);
    await writable.close();
  } catch (error) {
    await writable.abort?.();
    throw error;
  }
}

export async function writeVaultDocument(
  directory: FileSystemDirectoryHandle,
  document: VaultDocument,
  policy: VaultConflictPolicy,
): Promise<{ status: "written" | "kept"; filename: string }> {
  let filename = safeVaultFilename(document.filename.replace(/\.md$/i, ""));
  const existing = await findFile(directory, filename);
  if (existing) {
    if (policy === "keep") return { status: "kept", filename };
    if (policy === "copy") {
      const stem = filename.slice(0, -3);
      for (let index = 1; ; index += 1) {
        const candidate = `${stem}-${index}.md`;
        if (!(await findFile(directory, candidate))) {
          filename = candidate;
          break;
        }
      }
    }
  }
  const handle = await directory.getFileHandle(filename, { create: true });
  await writeFile(handle, document.markdown);
  return { status: "written", filename };
}

export function downloadVaultDocument(document: VaultDocument): string {
  const filename = safeVaultFilename(document.filename.replace(/\.md$/i, ""));
  const blob = new Blob([document.markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = window.document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
  return filename;
}

export async function exportToVault(
  document: VaultDocument,
  policy: VaultConflictPolicy,
): Promise<VaultWriteResult> {
  if (!window.showDirectoryPicker) {
    return {
      status: "downloaded",
      filename: downloadVaultDocument(document),
      reason: "当前浏览器不支持目录写入，已改为下载。",
    };
  }
  let directory: FileSystemDirectoryHandle;
  try {
    directory = await window.showDirectoryPicker({ id: "lifeos-vault", mode: "readwrite" });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return {
      status: "downloaded",
      filename: downloadVaultDocument(document),
      reason: "目录选择不可用或未授权，已改为下载，原文件未被覆盖。",
    };
  }
  if (directory.queryPermission && await directory.queryPermission({ mode: "readwrite" }) !== "granted") {
    return {
      status: "downloaded",
      filename: downloadVaultDocument(document),
      reason: "目录写入权限未授予，已改为下载，原文件未被覆盖。",
    };
  }
  const write = () => writeVaultDocument(directory, document, policy);
  try {
    return navigator.locks ? await navigator.locks.request("lifeos-vault-export", write) : await write();
  } catch (error) {
    if (error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError")) {
      return {
        status: "downloaded",
        filename: downloadVaultDocument(document),
        reason: "目录权限在写入时失效，已改为下载，原文件未被覆盖。",
      };
    }
    throw error;
  }
}
