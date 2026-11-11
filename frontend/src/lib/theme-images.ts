const DB_NAME = "crabagent-theme-images";
const STORE = "images";
export const IMAGE_PREFIX = "indexeddb:";

function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Image database is blocked"));
  });
}

async function transaction<T>(mode: IDBTransactionMode, operation: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database();
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const request = operation(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(request.result);
      tx.onabort = () => reject(tx.error || new Error("Image storage transaction aborted"));
      tx.onerror = () => reject(tx.error || new Error("Image storage failed"));
    });
  } finally { db.close(); }
}
export const putThemeImage = (id: string, image: Blob) => transaction("readwrite", store => store.put(image, id));
export const getThemeImage = (id: string): Promise<Blob | undefined> => transaction("readonly", store => store.get(id));
export const deleteThemeImage = (id: string) => transaction("readwrite", store => store.delete(id));
