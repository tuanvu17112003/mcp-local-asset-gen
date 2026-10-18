/**
 * UserProfile — React-only MVP sample consumer.
 *
 * Embeds the C1 `generate_app_asset` golden result (AC-1):
 *   asset_path: "assets/images/bear_avatar.png"
 *   category:   "avatar"
 *   prompt:     "cute bear avatar, 3D claymorphism, soft lighting"
 *   remove_bg:  true
 *
 * The PNG below is produced by the postprocess pipeline (C3) for stem
 * `bear_avatar` (1x 512x512 + exact 2x/3x multiples). See
 * `examples/react/README.md` for the asset file layout and join rule.
 */

import React from 'react';
import bearAvatar from '../../assets/images/bear_avatar.png';

export interface UserProfileProps {
  displayName?: string;
}

export function UserProfile({ displayName = 'Bear' }: UserProfileProps): JSX.Element {
  return (
    <div className="user-profile">
      <img src={bearAvatar} alt="Cute bear avatar" width={128} height={128} />
      <p>{displayName}</p>
    </div>
  );
}

export default UserProfile;
