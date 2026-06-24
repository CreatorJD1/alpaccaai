// Expo's Babel preset is all expo-router needs (it ships its own plugin via the
// preset). Kept minimal on purpose.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
  };
};
