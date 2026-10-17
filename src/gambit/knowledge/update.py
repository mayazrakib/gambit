import csv
import io

import httpx

from gambit.knowledge.base import Knowledge

def update_openings(
    knowledge: Knowledge,
    revision: str,
    client=None,
) -> dict:
    if len(revision,) != 40 or any((character not in '0123456789abcdef' for character in revision),):
        raise ValueError('Supply a full lowercase opening commit SHA.',)

    owns_client = client is None

    client = client or httpx.Client(
        timeout=15,
        follow_redirects=False,
    )

    rows = []
    total_bytes = 0

    try:
        for letter in 'abcde':
            url = f'https://raw.githubusercontent.com/lichess-org/chess-openings/{revision}/{letter}.tsv'
            content = bytearray()

            with client.stream(
                'GET',
                url,
            ) as response:
                response.raise_for_status()

                for chunk in response.iter_bytes():
                    total_bytes += len(chunk,)

                    if total_bytes > 16 * 1024 * 1024:
                        raise ValueError('The complete opening download exceeds 16 MiB.',)

                    content.extend(chunk,)

            parsed = list(csv.DictReader(
                io.StringIO(content.decode(),),
                delimiter='\t',
            ),)

            if not parsed or any((not row['eco'].startswith(letter.upper(),) for row in parsed),):
                raise ValueError('The opening volume does not match its ECO classification.',)

            rows.extend(parsed,)

        return knowledge.publish(
            revision,
            rows,
        )
    finally:
        if owns_client:
            client.close()
