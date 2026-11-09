#!/usr/bin/env bash
# Le SSD du Pi, une fois (docs/exploitation/pi.md) : EFFACE le disque donné, le chiffre (LUKS2),
# le monte sur /srv/ssd et y déplace le dossier de Docker (le hub et Domia avec lui).
#   sudo deploy/pi-ssd-setup.sh /dev/sdX
# Déverrouillage au démarrage par une clé sur la carte SD (/etc/cryptsetup-keys.d/hubssd.key) :
# tout redémarre seul après une coupure, Domia compris. Une phrase de secours est ajoutée
# au chiffrement : à noter dans le kit de secours. L'ancien dossier de Docker est gardé
# (/var/lib/docker.avant-ssd) jusqu'à ce que tout tourne ; le supprimer ensuite à la main.
set -euo pipefail

DEV="${1:?usage: sudo deploy/pi-ssd-setup.sh /dev/sdX (lsblk pour le trouver)}"
NAME=hubssd
MNT=/srv/ssd
KEY=/etc/cryptsetup-keys.d/$NAME.key
OWNER="${SUDO_USER:?lancer avec sudo depuis le compte qui porte le hub}"

[ "$(id -u)" = 0 ] || { echo "lancer avec sudo"; exit 1; }
[ -b "$DEV" ] || { echo "$DEV n'est pas un disque"; exit 1; }
case "$DEV" in /dev/mmcblk*) echo "$DEV est la carte SD : refusé"; exit 1 ;; esac
[ "$(lsblk -dno TRAN "$DEV")" = usb ] || [[ "$DEV" == /dev/nvme* ]] \
  || { echo "$DEV n'est ni USB ni NVMe : refusé"; exit 1; }
if lsblk -no MOUNTPOINT "$DEV" | grep -q .; then
  echo "$DEV a une partition montée : la démonter d'abord"; exit 1
fi
command -v cryptsetup >/dev/null || apt-get install -y cryptsetup
command -v rsync >/dev/null || apt-get install -y rsync

lsblk -o NAME,SIZE,MODEL,TRAN "$DEV"
read -r -p "Tout ce qui est sur $DEV sera EFFACÉ. Taper EFFACER pour continuer : " ok
[ "$ok" = EFFACER ] || { echo "rien n'a changé"; exit 1; }

echo "==> Partition et chiffrement"
wipefs -a "$DEV"
parted -s "$DEV" mklabel gpt mkpart "$NAME" 1MiB 100%
udevadm settle
PART="$(lsblk -lnpo NAME "$DEV" | sed -n 2p)"
install -d -m 0700 /etc/cryptsetup-keys.d
( umask 077; head -c 64 /dev/urandom > "$KEY" )
chmod 0400 "$KEY"
cryptsetup luksFormat --type luks2 --batch-mode --key-file "$KEY" "$PART"
echo "Phrase de secours (à noter dans le kit de secours) :"
cryptsetup luksAddKey --key-file "$KEY" "$PART"
cryptsetup open --key-file "$KEY" "$PART" "$NAME"
mkfs.ext4 -q -L "$NAME" "/dev/mapper/$NAME"

echo "==> Montage au démarrage"
UUID="$(cryptsetup luksUUID "$PART")"
grep -q "^$NAME " /etc/crypttab 2>/dev/null \
  || echo "$NAME UUID=$UUID $KEY luks,discard,nofail" >> /etc/crypttab
grep -q " $MNT " /etc/fstab \
  || echo "/dev/mapper/$NAME $MNT ext4 defaults,noatime,nofail,x-systemd.device-timeout=60 0 2" >> /etc/fstab
mkdir -p "$MNT"
systemctl daemon-reload
mount "$MNT"

echo "==> Docker sur le SSD (le hub et Domia s'arrêtent quelques minutes)"
systemctl stop docker.socket docker.service
rsync -aHAX --info=progress2 /var/lib/docker/ "$MNT/docker/"
mv /var/lib/docker /var/lib/docker.avant-ssd
mkdir -p /var/lib/docker
python3 - "$MNT/docker" <<'EOF'
import json, pathlib, sys
p = pathlib.Path("/etc/docker/daemon.json")
conf = json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
conf["data-root"] = sys.argv[1]
p.parent.mkdir(exist_ok=True)
p.write_text(json.dumps(conf, indent=2) + "\n")
EOF
# Docker attend le SSD : sans lui, il ne démarre pas sur un dossier vide de la carte SD
install -d /etc/systemd/system/docker.service.d
printf '[Unit]\nRequiresMountsFor=%s\n' "$MNT" > /etc/systemd/system/docker.service.d/ssd.conf
systemctl daemon-reload
systemctl start docker

echo "==> Dossiers du hub"
install -d -o "$OWNER" -g "$OWNER" "$MNT/hub" "$MNT/hub/inbox" "$MNT/hub/backup" \
  "$MNT/hub/backup/litestream" "$MNT/hub/backup/restic"

docker info --format 'Docker : {{.DockerRootDir}}'
docker ps --format '{{.Names}} {{.Status}}'
echo "Prêt. Vérifier Domia, puis : sudo rm -rf /var/lib/docker.avant-ssd"
