"""Collecteurs (lot 5) : téléchargeurs d'exports officiels qui déposent dans la boîte d'entrée.

Ils tournent dans leurs propres conteneurs, qui ne montent que la boîte d'entrée et leur
profil : ils ne voient aucune base, ne lisent aucune donnée à l'écran, et ne déclarent que le
résultat de chaque run au hub (`POST /api/collectors/{nom}/runs`). Toute la lecture des
fichiers passe ensuite par les parseurs du domaine Finance.
"""
