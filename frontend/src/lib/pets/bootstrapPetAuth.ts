interface PetAuthClient {
  setToken: (token: string) => void;
}

/** Authenticate the separate pet renderer before mounting API consumers. */
export async function bootstrapPetAuth(
  client: PetAuthClient,
  getToken?: () => Promise<string | null>,
): Promise<void> {
  if (!getToken) return;
  const token = await getToken();
  if (!token) throw new Error("Pet authentication is not ready");
  client.setToken(token);
}
