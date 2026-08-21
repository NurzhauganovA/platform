/**
 * Подготовка папки к загрузке.
 *
 * Браузер считает sha256 каждого файла, не отправляя его. Платформа отвечает,
 * что из этого вообще нужно грузить: неподдерживаемые форматы отсеиваются, а
 * уже загруженное не передаётся повторно.
 *
 * На папке в тринадцать мегабайт это экономит секунды, на архиве в два
 * гигабайта — часы и трафик. И то же самое отвечает на вопрос «сколько будет
 * стоить разбор» до того, как деньги потрачены: содержимое, которое ядро уже
 * разбирало, второй раз не оплачивается.
 */

import { tender, type FileProbe, type UploadPlan } from "@/api/tender";

/** Файл из выбранной папки вместе с путём внутри неё. */
export interface PickedFile {
  file: File;
  relativePath: string;
  sha256: string;
}

/**
 * sha256 содержимого.
 *
 * Итог должен совпасть с тем, что посчитает сервер: расхождение означает,
 * что содержимое подменили, и загрузка будет отклонена.
 */
export async function hashFile(file: File): Promise<string> {
  // WebCrypto не умеет считать по частям, поэтому собираем буфер сами.
  // Для файлов до нашего потолка в 64 МБ этого достаточно.
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function relativePathOf(file: File): string {
  // webkitRelativePath приходит с именем корневой папки впереди — его
  // отбрасываем: внутри закупки путь считается от неё самой, а подпапки
  // («обновленные кп») сохраняются, по ним ядро отличает состав закупок.
  const full =
    (file as File & { webkitRelativePath?: string }).webkitRelativePath ||
    file.name;
  const parts = full.split("/");
  return parts.length > 1 ? parts.slice(1).join("/") : full;
}

export function folderNameOf(files: File[]): string {
  const first = files[0] as
    (File & { webkitRelativePath?: string }) | undefined;
  const full = first?.webkitRelativePath ?? "";
  return full.split("/")[0] ?? "";
}

/** Служебный мусор macOS и Windows, которого в папках заказчиков полно. */
const JUNK = new Set([".DS_Store", "Thumbs.db", "desktop.ini"]);

export function isJunk(file: File): boolean {
  return (
    JUNK.has(file.name) ||
    file.name.startsWith("~$") ||
    file.name.startsWith("._")
  );
}

export async function prepare(
  files: File[],
  onProgress?: (done: number, total: number) => void,
): Promise<PickedFile[]> {
  const useful = files.filter((file) => !isJunk(file) && file.size > 0);
  const picked: PickedFile[] = [];

  for (const [index, file] of useful.entries()) {
    picked.push({
      file,
      relativePath: relativePathOf(file),
      sha256: await hashFile(file),
    });
    onProgress?.(index + 1, useful.length);
  }
  return picked;
}

export function toProbes(picked: PickedFile[]): FileProbe[] {
  return picked.map((item) => ({
    name: item.file.name,
    relative_path: item.relativePath,
    size_bytes: item.file.size,
    sha256: item.sha256,
  }));
}

export async function planUpload(picked: PickedFile[]): Promise<UploadPlan> {
  return tender.uploadPlan(toProbes(picked));
}

/**
 * Загружает то, что действительно нужно.
 *
 * Файлы идут по одному, а не пачкой: так виден прогресс и обрыв связи стоит
 * одного файла, а не всей папки.
 */
export async function upload(
  picked: PickedFile[],
  plan: UploadPlan,
  onProgress?: (done: number, total: number, name: string) => void,
): Promise<{ file_id: string; relative_path: string }[]> {
  const keep = plan.files.filter((item) => item.supported);
  const known = new Set(
    keep.filter((item) => item.known).map((item) => item.relative_path),
  );
  const paths = new Set(keep.map((item) => item.relative_path));
  const queue = picked.filter((item) => paths.has(item.relativePath));

  // Уже загруженное к закупке всё равно прикрепляется, но передавать его
  // повторно незачем: идентификатор находится по содержимому. Без этого шага
  // весь смысл плана терялся бы на самом главном месте.
  const existing = new Map<string, string>();
  const knownHashes = queue
    .filter((item) => known.has(item.relativePath))
    .map((i) => i.sha256);
  if (knownHashes.length) {
    for (const row of await tender.lookupFiles(knownHashes))
      existing.set(row.sha256, row.id);
  }

  const attached: { file_id: string; relative_path: string }[] = [];
  for (const [index, item] of queue.entries()) {
    onProgress?.(index, queue.length, item.file.name);

    const cached = existing.get(item.sha256);
    const fileId =
      cached ??
      (await tender.uploadFile(item.file, item.relativePath, item.sha256)).id;
    attached.push({ file_id: fileId, relative_path: item.relativePath });
  }
  onProgress?.(queue.length, queue.length, "");
  return attached;
}
