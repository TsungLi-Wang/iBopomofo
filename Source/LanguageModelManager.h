// Copyright (c) 2022 and onwards The McBopomofo Authors.
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the
// Software is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
// OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
// WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.

#import <Foundation/Foundation.h>
#import "KeyHandler.h"

NS_ASSUME_NONNULL_BEGIN

@interface LanguageModelManager : NSObject

+ (void)loadDataModel:(InputMode)mode;
+ (void)loadUserPhrasesWithPlainBopomofoEnabled:(BOOL)userPhraseForPlainBopomofo NS_SWIFT_NAME(loadUserPhrases(enableForPlainBopomofo:));
+ (void)loadUserPhraseReplacement;
+ (void)setupDataModelValueConverter;
+ (BOOL)checkIfUserLanguageModelFilesExist;

+ (BOOL)checkIfUserPhraseExist:(NSString *)userPhrase key:(NSString *)key NS_SWIFT_NAME(checkIfExist(userPhrase:key:));
+ (BOOL)writeUserPhrase:(NSString *)userPhrase;
+ (BOOL)removeUserPhrase:(NSString *)userPhrase;

+ (nullable NSString *)readingFor:(NSString *)phrase;

/// Homophone candidates for a single committed character (post-commit reselect).
/// Returns NSArray of InputStateCandidate-compatible dicts:
///   @{ @"reading": NSString, @"value": NSString, @"displayText": NSString }
/// Empty array if the character has no reading in the model (caller should degrade).
+ (NSArray<NSDictionary<NSString *, NSString *> *> *)homophoneCandidatesForCharacter:(NSString *)character
    NS_SWIFT_NAME(homophoneCandidates(forCharacter:));

@property (class, readonly, nonatomic) NSString *dataFolderPath;
@property (class, readonly, nonatomic) NSString *userPhrasesDataPathMcBopomofo;
@property (class, readonly, nonatomic) NSString *userPhrasesDataPathPlainBopomofo;
@property (class, readonly, nonatomic) NSString *excludedPhrasesDataPathMcBopomofo;
@property (class, readonly, nonatomic) NSString *excludedPhrasesDataPathPlainBopomofo;
@property (class, readonly, nonatomic) NSString *phraseReplacementDataPathMcBopomofo;
@property (class, readonly, nonatomic) NSString *userOverrideCachePath;
@property (class, assign, nonatomic) BOOL phraseReplacementEnabled;

/// Load/save private personalization cache (user data folder only).
+ (void)loadUserOverrideCache;
+ (void)saveUserOverrideCache;

/// Walk-independent soft personalization (e.g. post-commit delete-and-recompose).
/// One call reaches soft threshold (count ≥ 2). Saves cache on success.
/// Returns NO if reading/word empty (no-op). Never throws.
+ (BOOL)noteSoftPersonalizationWithPrevious:(NSString *)previous
                                    reading:(NSString *)reading
                                       word:(NSString *)word
    NS_SWIFT_NAME(noteSoftPersonalization(previous:reading:word:));

@end

/// The following methods are merely for testing.
@interface LanguageModelManager ()
+ (void)loadDataModels;
@end

@interface LanguageModelManager ()
+ (NSString *)annotateVariantForCharacters:(NSString *)characters readings:(NSString *)readings NS_SWIFT_NAME(annotateVariant(characters:readings:));
@end

NS_ASSUME_NONNULL_END
